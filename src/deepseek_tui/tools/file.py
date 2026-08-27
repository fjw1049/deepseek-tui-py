

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.utils.edit_diagnostics import build_edit_no_match_message
from deepseek_tui.tools.utils.path_suggestions import format_not_found_error
from deepseek_tui.tools.utils.sensitive import is_sensitive_path, is_sensitive_write_path
from deepseek_tui.tools.utils.validation import require_string as _require_string
from deepseek_tui.utils import write_text_atomic

logger = logging.getLogger(__name__)

# read_file output guardrails (Claude Code Read parity): page size and
# per-line width. The page cap bounds what we return; the scan cap bounds
# how far we will walk to reach an offset. Skipped prefix bytes are not
# charged against the page.
_DEFAULT_READ_LIMIT = 2000
_MAX_READ_LINE_LEN = 2000
_MAX_READ_FILE_BYTES = 1024 * 1024
_MAX_READ_SCAN_BYTES = 64 * 1024 * 1024


class ReadFileTool(ToolSpec):
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "Read a UTF-8 text file from disk. Output is line-numbered "
            "(cat -n style). By default at most 2000 lines are returned and "
            "lines longer than 2000 characters are truncated; use offset/limit "
            "to page through large files in ranges. Files larger than 1 MiB "
            "that cannot be paged within that budget are rejected. Do not use "
            "this on a directory — list entries with file_search or "
            "`exec_shell ls` instead. Prefer reading a file before editing it "
            "so a later stale-write check can catch concurrent changes."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "File to read, workspace-relative (e.g. "
                        "'src/app.py'). Absolute only if the user gave one."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Optional 1-based starting line number; 0 means the "
                        "beginning of the file."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Optional maximum number of lines to return "
                        "(default 2000)."
                    ),
                },
            },
            "required": ["path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        rel = _require_string(input_data, "path")
        path = context.resolve_path(rel, allow_read_roots=True)
        if is_sensitive_path(path):
            raise ToolError(
                f"refusing to read sensitive file: {path} "
                "(matched the credential-file blocklist)"
            )
        offset = _optional_non_negative_int(input_data, "offset")
        limit = _optional_non_negative_int(input_data, "limit")
        start = max((offset or 0) - 1, 0)
        effective_limit = _DEFAULT_READ_LIMIT if limit is None else limit
        page = await asyncio.to_thread(
            _read_text_page,
            path,
            start,
            effective_limit,
            display_path=rel,
            cwd=context.working_directory,
        )
        numbered: list[str] = []
        for line_no, line in page.lines:
            if len(line) > _MAX_READ_LINE_LEN:
                line = line[:_MAX_READ_LINE_LEN] + "... (line truncated)"
            numbered.append(f"{line_no}\t{line}")
        if page.has_more:
            start_display = start + 1
            end_display = start + len(page.lines)
            if page.total_lines is not None:
                numbered.append(
                    f"... (showing lines {start_display}-{end_display} of "
                    f"{page.total_lines}; use offset to continue)"
                )
            else:
                numbered.append(
                    f"... (showing lines {start_display}-{end_display}; "
                    "use offset to continue)"
                )
        context.note_file_content(path)
        metadata: dict[str, object] = {
            "path": str(path),
            "line_offset": offset or 0,
            "line_limit": effective_limit,
        }
        if page.total_lines is not None:
            metadata["total_lines"] = page.total_lines
        logger.info("read_file path=%s bytes_scanned=%d", path, page.bytes_scanned)
        return ToolResult(success=True, content="\n".join(numbered), metadata=metadata)


class WriteFileTool(ToolSpec):
    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return (
            "Write UTF-8 text to a file on disk. New files can be written "
            "directly. Existing files may be overwritten without a prior "
            "read_file; if this session already read the file and it changed "
            "on disk since then, the write is refused so concurrent edits are "
            "not discarded. Prefer this (or edit_file) for source changes — "
            "do not rewrite files via exec_shell. Use this only for new files "
            "or full rewrites; for partial changes use edit_file. "
            "Paths are workspace-relative: path=\"notes.md\" lands at "
            "<workspace>/notes.md. Do not use ~/ or absolute paths outside "
            "the workspace — they are rejected."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Destination, workspace-relative: 'notes.md' lands "
                        "at <workspace>/notes.md. Throwaway scripts and "
                        "drafts go under 'scratch/'."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Complete file content (UTF-8). This replaces the "
                        "whole file — never write placeholders like "
                        "'... rest unchanged'."
                    ),
                },
            },
            "required": ["path", "content"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        from deepseek_tui.workspace.diff_synth import synthesize_unified_diff
        from deepseek_tui.workspace.mutation_ledger import build_mutation_metadata

        rel = _require_string(input_data, "path")
        path = context.resolve_path(rel)
        content = _require_string(input_data, "content")
        if is_sensitive_write_path(path):
            raise ToolError(
                f"refusing to write sensitive file: {path} "
                "(matched the credential-file blocklist)"
            )
        if context.changed_since_last_seen(path):
            raise ToolError(_stale_write_message(path))
        existed = path.exists()
        old_text = ""
        if existed:
            try:
                old_text = await _read_text(path)
            except (OSError, ToolError):
                # Race: vanished between exists() and read — treat as empty.
                old_text = ""
        context.capture_pre_write(
            _workspace_rel(path, context.working_directory, rel),
            old_text if existed else None,
        )
        await _write_text(path, content)
        context.note_file_content(path)
        logger.info("write_file path=%s bytes=%d", path, len(content))
        display_path = _workspace_rel(path, context.working_directory, rel)
        unified, stats, op = synthesize_unified_diff(display_path, old_text, content)
        meta = build_mutation_metadata(
            path=display_path,
            op=op,  # type: ignore[arg-type]
            unified_diff=unified,
            additions=stats.additions,
            deletions=stats.deletions,
            source="write_file",
            line_start=1,  # whole file replaced/created
        )
        context.report_file_mutation(
            {
                **meta["mutation"],
                "_before_content": old_text if existed else None,
                "_after_content": content,
            }
        )
        return ToolResult(success=True, content="ok", metadata=meta)


class EditFileTool(ToolSpec):
    """Replace text in a UTF-8 file via exact string replacement."""

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "Perform exact string replacement in a single file. Fails if "
            "old_string is not found, or if it is not unique unless "
            "replace_all is true. Prefer reading the file first: if this "
            "session already read it and the file changed on disk, the edit "
            "is refused even when old_string still matches. "
            "Prefer this over sed/python via exec_shell for source edits. "
            "For a brand-new file use write_file instead."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File to edit, workspace-relative.",
                },
                "old_string": {
                    "type": "string",
                    "description": (
                        "Exact text to replace, copied verbatim from a "
                        "read_file result (match indentation exactly; never "
                        "include line-number prefixes). Must be unique in "
                        "the file unless replace_all=true — include enough "
                        "surrounding lines to make it unique."
                    ),
                },
                "new_string": {
                    "type": "string",
                    "description": (
                        "Replacement text (must differ from old_string)."
                    ),
                },
                "replace_all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Replace all occurrences of old_string (default false)",
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        from deepseek_tui.workspace.diff_synth import synthesize_unified_diff
        from deepseek_tui.workspace.mutation_ledger import build_mutation_metadata

        rel = _require_string(input_data, "path")
        path = context.resolve_path(rel)
        old_string = _require_string_with_alias(input_data, "old_string", "search")
        new_string = _require_string_with_alias(input_data, "new_string", "replace")
        if is_sensitive_write_path(path):
            raise ToolError(
                f"refusing to write sensitive file: {path} "
                "(matched the credential-file blocklist)"
            )
        replace_all = input_data.get("replace_all", False)
        if not isinstance(replace_all, bool):
            raise ToolError("replace_all must be a boolean")
        # Empty old_string matches every character gap in str.replace/count and
        # would rewrite the entire file — reject before touching disk.
        if old_string == "":
            raise ToolError("edit_file old_string must not be empty")
        content = await _read_text(
            path,
            display_path=rel,
            cwd=context.working_directory,
        )
        count = content.count(old_string)
        if count == 0:
            logger.warning("edit_file_no_match path=%s search_len=%d", path, len(old_string))
            # A no-match on a file that moved on disk has a specific cause and
            # a specific fix. Saying only "not found" sends the model hunting
            # for a typo in old_string that isn't there.
            if context.changed_since_last_seen(path):
                raise ToolError(_stale_write_message(path))
            raise ToolError(build_edit_no_match_message(path, old_string, content))
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string occurs {count} times in {path}; provide more "
                "surrounding context to make it unique, or set "
                "replace_all=true to change every instance"
            )
        if context.changed_since_last_seen(path):
            raise ToolError(_stale_write_message(path))
        updated = content.replace(old_string, new_string)
        context.capture_pre_write(
            _workspace_rel(path, context.working_directory, rel), content
        )
        await _write_text(path, updated)
        context.note_file_content(path)
        display_path = _workspace_rel(path, context.working_directory, rel)
        summary = f"Replaced {count} occurrence(s) in {display_path}"
        logger.info(
            "edit_file path=%s search_len=%d replace_len=%d count=%d",
            path,
            len(old_string),
            len(new_string),
            count,
        )
        unified, stats, op = synthesize_unified_diff(display_path, content, updated)
        first_idx = content.find(old_string)
        line_start = content[:first_idx].count("\n") + 1 if first_idx >= 0 else None
        meta = build_mutation_metadata(
            path=display_path,
            op=op,  # type: ignore[arg-type]
            unified_diff=unified,
            additions=stats.additions,
            deletions=stats.deletions,
            source="edit_file",
            line_start=line_start,
        )
        meta["occurrences"] = count
        context.report_file_mutation(
            {
                **meta["mutation"],
                "_before_content": content,
                "_after_content": updated,
            }
        )
        return ToolResult(
            success=True,
            content=summary,
            metadata=meta,
        )


def _stale_write_message(path: Path) -> str:
    """Explain the staleness and give the one action that clears it."""
    return (
        f"{path} changed on disk after you last read it — a formatter, a "
        "shell command, another agent, or the user edited it. Writing now "
        "would silently discard that change. Run read_file on it, then "
        "redo this write against what is actually there."
    )


def _require_string_with_alias(
    input_data: dict[str, object], primary: str, alias: str
) -> str:
    """Accept primary key, fall back to alias (for schema migration).

    Used by ``edit_file`` to accept both ``old_string``/``new_string``
    and legacy ``search``/``replace`` so models trained on either
    schema still work.
    """
    if primary in input_data:
        value = input_data[primary]
    elif alias in input_data:
        value = input_data[alias]
    else:
        raise ToolError(f"{primary} (or {alias}) must be provided")
    if not isinstance(value, str):
        raise ToolError(f"{primary} must be a string")
    return value


def _optional_non_negative_int(
    input_data: dict[str, object], key: str
) -> int | None:
    if key not in input_data:
        return None
    value = input_data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{key} must be a non-negative integer")
    if value < 0:
        raise ToolError(f"{key} must be a non-negative integer")
    return value


def _workspace_rel(path: Path, workspace: Path, fallback: str) -> str:
    try:
        return str(path.resolve().relative_to(workspace.expanduser().resolve())).replace(
            "\\", "/"
        )
    except ValueError:
        return fallback.replace("\\", "/")


@dataclass(frozen=True, slots=True)
class _ReadPage:
    lines: list[tuple[int, str]]
    total_lines: int | None
    has_more: bool
    bytes_scanned: int


def _not_found_error(
    path: Path,
    *,
    display_path: str | None,
    cwd: Path | None,
) -> ToolError:
    if cwd is None:
        return ToolError(f"Error: {display_path or path} does not exist.")
    return ToolError(
        format_not_found_error(
            display_path=display_path or str(path),
            resolved_path=path,
            cwd=cwd,
        )
    )


def _read_text_page(
    path: Path,
    start: int,
    limit: int,
    *,
    display_path: str | None = None,
    cwd: Path | None = None,
) -> _ReadPage:
    """Read a line window without loading the whole file into memory."""
    if path.is_dir():
        raise ToolError(
            f"{display_path or path} is a directory. Use file_search or exec_shell ls."
        )
    label = display_path or str(path)
    try:
        fh = path.open("rb")
    except FileNotFoundError as exc:
        raise _not_found_error(path, display_path=display_path, cwd=cwd) from exc
    except OSError as exc:
        raise ToolError(f"Error reading {label}: {exc}") from exc

    page: list[tuple[int, str]] = []
    line_no = 0
    bytes_scanned = 0
    page_bytes = 0
    scan_stopped = False
    page_oversize = False
    buf = b""

    def _decode_line(raw: bytes) -> str:
        if b"\x00" in raw:
            raise ToolError(f"{label} is not a UTF-8 text file.")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"{label} is not a UTF-8 text file.") from exc

    def _take_line(raw: bytes) -> None:
        nonlocal line_no, page_bytes, page_oversize
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        line_no += 1
        if start < line_no <= start + limit:
            page.append((line_no, _decode_line(raw)))
            page_bytes += len(raw)
            if page_bytes > _MAX_READ_FILE_BYTES:
                page_oversize = True

    try:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                if buf:
                    _take_line(buf)
                break
            if b"\x00" in chunk:
                raise ToolError(f"{label} is not a UTF-8 text file.")
            bytes_scanned += len(chunk)
            buf += chunk
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                raw = buf[:nl]
                buf = buf[nl + 1 :]
                _take_line(raw)
            if page_oversize:
                break
            if bytes_scanned > _MAX_READ_SCAN_BYTES:
                scan_stopped = True
                break
    finally:
        fh.close()

    if line_no <= start:
        raise ToolError(
            f"{label} exceeds the read scan budget before offset {start + 1} "
            "could be reached. Use exec_shell (e.g. sed) to read further."
        )
    if page_oversize:
        raise ToolError(
            f"{label} exceeds the {_MAX_READ_FILE_BYTES} byte read limit "
            "before this page could be finished. Use a smaller limit, "
            "or exec_shell for binary/large files."
        )
    has_more = line_no > start + len(page) or scan_stopped
    total = None if scan_stopped else line_no
    return _ReadPage(page, total, has_more, bytes_scanned)


async def _read_text(
    path: Path,
    *,
    display_path: str | None = None,
    cwd: Path | None = None,
) -> str:
    """Read UTF-8 text; enrich FileNotFound with path suggestions when possible."""
    try:
        return await asyncio.to_thread(path.read_text, encoding="utf-8")
    except FileNotFoundError as exc:
        raise _not_found_error(path, display_path=display_path, cwd=cwd) from exc


async def _write_text(path: Path, content: str) -> None:
    await asyncio.to_thread(write_text_atomic, path, content)
