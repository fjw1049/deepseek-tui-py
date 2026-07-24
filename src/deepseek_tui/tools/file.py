

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from deepseek_tui.tools.validation import require_string as _require_string
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.utils import write_text_atomic

logger = logging.getLogger(__name__)

# read_file output guardrails (Claude Code Read parity): page size and
# per-line width.
_DEFAULT_READ_LIMIT = 2000
_MAX_READ_LINE_LEN = 2000


class ReadFileTool(ToolSpec):
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "Read a UTF-8 text file from disk. Output is line-numbered "
            "(cat -n style). By default at most 2000 lines are returned and "
            "lines longer than 2000 characters are truncated; use offset/limit "
            "to page through large files in ranges."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
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
        path = context.resolve_path(_require_string(input_data, "path"), allow_read_roots=True)
        content = await _read_text(path)
        offset = _optional_non_negative_int(input_data, "offset")
        limit = _optional_non_negative_int(input_data, "limit")
        all_lines = content.splitlines()
        total_lines = len(all_lines)
        start = max((offset or 0) - 1, 0)
        effective_limit = _DEFAULT_READ_LIMIT if limit is None else limit
        end = start + effective_limit
        numbered: list[str] = []
        for line_no, line in enumerate(all_lines[start:end], start=start + 1):
            if len(line) > _MAX_READ_LINE_LEN:
                line = line[:_MAX_READ_LINE_LEN] + "... (line truncated)"
            numbered.append(f"{line_no}\t{line}")
        if end < total_lines:
            numbered.append(
                f"... (showing lines {start + 1}-{end} of {total_lines}; "
                "use offset to continue)"
            )
        metadata: dict[str, object] = {
            "path": str(path),
            "line_offset": offset or 0,
            "line_limit": effective_limit,
            "total_lines": total_lines,
        }
        logger.info("read_file path=%s bytes=%d", path, len(content))
        return ToolResult(success=True, content="\n".join(numbered), metadata=metadata)


class WriteFileTool(ToolSpec):
    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return (
            "Write UTF-8 text to a file on disk. If the file already exists, "
            "you must have used read_file on it earlier in the conversation "
            "before overwriting it; new files can be written directly. "
            "Prefer this (or edit_file) for source changes — do not rewrite "
            "files via exec_shell."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
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
        existed = path.exists()
        old_text = ""
        if existed:
            try:
                old_text = await _read_text(path)
            except OSError:
                old_text = ""
        context.capture_pre_write(
            _workspace_rel(path, context.working_directory, rel),
            old_text if existed else None,
        )
        await _write_text(path, content)
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
        context.report_file_mutation(meta["mutation"])
        return ToolResult(success=True, content="ok", metadata=meta)


class EditFileTool(ToolSpec):
    """Replace text in a UTF-8 file via exact string replacement."""

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "Perform exact string replacement in a single file. Fails if "
            "old_string is not found, or if it is not unique unless "
            "replace_all is true. You must have used read_file on this file "
            "earlier in the conversation before editing it. "
            "Prefer this over sed/python via exec_shell for source edits."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string", "description": "Text to replace."},
                "new_string": {"type": "string", "description": "Replacement text."},
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
        replace_all = input_data.get("replace_all", False)
        if not isinstance(replace_all, bool):
            raise ToolError("replace_all must be a boolean")
        # Empty old_string matches every character gap in str.replace/count and
        # would rewrite the entire file — reject before touching disk.
        if old_string == "":
            raise ToolError("edit_file old_string must not be empty")
        content = await _read_text(path)
        count = content.count(old_string)
        if count == 0:
            logger.warning("edit_file_no_match path=%s search_len=%d", path, len(old_string))
            raise ToolError(f"Search string not found in {path}")
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string occurs {count} times in {path}; provide more "
                "surrounding context to make it unique, or set "
                "replace_all=true to change every instance"
            )
        updated = content.replace(old_string, new_string)
        context.capture_pre_write(
            _workspace_rel(path, context.working_directory, rel), content
        )
        await _write_text(path, updated)
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
        context.report_file_mutation(meta["mutation"])
        return ToolResult(
            success=True,
            content=summary,
            metadata=meta,
        )


class ListDirTool(ToolSpec):
    def name(self) -> str:
        return "list_dir"

    def description(self) -> str:
        return (
            "List entries in a directory relative to the workspace. "
            "Returns structured JSON with name and is_dir fields."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path (default: .)",
                }
            },
            "required": [],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        import json

        raw_path = input_data.get("path")
        path_str = raw_path if isinstance(raw_path, str) and raw_path.strip() else "."
        # READ_ONLY tool: pass allow_read_roots=True so a mounted plugin's
        # own directory (granted via ToolContext.extra_read_roots) is listable
        # just like read_file/grep_files. Without this, list_dir on the plugin
        # dir is rejected as "path escapes workspace" even when mounted.
        path = context.resolve_path(path_str, allow_read_roots=True)
        entries = await _list_dir_structured(path)
        payload = json.dumps(entries, ensure_ascii=False, indent=2)
        return ToolResult(
            success=True,
            content=payload,
            metadata={"path": str(path), "count": len(entries)},
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


async def _read_text(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")


async def _write_text(path: Path, content: str) -> None:
    await asyncio.to_thread(write_text_atomic, path, content)


async def _list_dir_structured(path: Path) -> list[dict[str, object]]:
    def _scan() -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for entry in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            rows.append({"name": entry.name, "is_dir": is_dir})
        return rows

    return await asyncio.to_thread(_scan)
