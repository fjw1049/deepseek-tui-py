

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from deepseek_tui.tools.validation import require_string as _require_string
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.utils import write_text_atomic

logger = logging.getLogger(__name__)


class ReadFileTool(ToolSpec):
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "Read a UTF-8 text file from disk. Use offset/limit to read a "
            "specific line range instead of loading large files in full."
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
                    "description": "Optional maximum number of lines to return.",
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
        metadata: dict[str, object] = {"path": str(path)}
        if offset is not None or limit is not None:
            lines = content.splitlines(keepends=True)
            start = max((offset or 0) - 1, 0)
            end = None if limit is None else start + limit
            content = "".join(lines[start:end])
            metadata.update(
                {
                    "line_offset": offset or 0,
                    "line_limit": limit,
                    "total_lines": len(lines),
                }
            )
        logger.info("read_file path=%s bytes=%d", path, len(content))
        return ToolResult(success=True, content=content, metadata=metadata)


class WriteFileTool(ToolSpec):
    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return (
            "Write UTF-8 text to a file on disk. Prefer this (or edit_file / "
            "apply_patch) for source changes — do not rewrite files via exec_shell."
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
        old_text = ""
        if path.exists():
            try:
                old_text = await _read_text(path)
            except OSError:
                old_text = ""
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
    """Replace text in a UTF-8 file via exact search/replace (all occurrences)."""

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "Replace text in a single file via exact search/replace. "
            "Use 'search' and 'replace'; all occurrences of search are substituted. "
            "Prefer this over sed/python via exec_shell for source edits."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "search": {"type": "string", "description": "Text to find."},
                "replace": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "search", "replace"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        from deepseek_tui.workspace.diff_synth import synthesize_unified_diff
        from deepseek_tui.workspace.mutation_ledger import build_mutation_metadata

        rel = _require_string(input_data, "path")
        path = context.resolve_path(rel)
        search = _require_string_with_alias(input_data, "search", "old_string")
        replace = _require_string_with_alias(input_data, "replace", "new_string")
        # Empty search matches every character gap in str.replace/count and
        # would rewrite the entire file — reject before touching disk.
        if search == "":
            raise ToolError("edit_file search string must not be empty")
        content = await _read_text(path)
        count = content.count(search)
        if count == 0:
            logger.warning("edit_file_no_match path=%s search_len=%d", path, len(search))
            raise ToolError(f"Search string not found in {path}")
        updated = content.replace(search, replace)
        await _write_text(path, updated)
        display_path = _workspace_rel(path, context.working_directory, rel)
        summary = f"Replaced {count} occurrence(s) in {display_path}"
        logger.info(
            "edit_file path=%s search_len=%d replace_len=%d count=%d",
            path,
            len(search),
            len(replace),
            count,
        )
        unified, stats, op = synthesize_unified_diff(display_path, content, updated)
        first_idx = content.find(search)
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

    Used by ``edit_file`` to accept both ``search``/``replace``
    and legacy ``old_string``/``new_string`` so models trained on either
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
