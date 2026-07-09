

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
        return "Write UTF-8 text to a file on disk."

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
        path = context.resolve_path(_require_string(input_data, "path"))
        content = _require_string(input_data, "content")
        await _write_text(path, content)
        logger.info("write_file path=%s bytes=%d", path, len(content))
        return ToolResult(success=True, content="ok", metadata={"path": str(path)})


class EditFileTool(ToolSpec):
    """Replace text in a UTF-8 file via exact search/replace (all occurrences)."""

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "Replace text in a single file via exact search/replace. "
            "Use 'search' and 'replace'; all occurrences of search are substituted."
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
        path = context.resolve_path(_require_string(input_data, "path"))
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
        summary = f"Replaced {count} occurrence(s) in {path}"
        logger.info(
            "edit_file path=%s search_len=%d replace_len=%d count=%d",
            path,
            len(search),
            len(replace),
            count,
        )
        return ToolResult(
            success=True,
            content=summary,
            metadata={"path": str(path), "occurrences": count},
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
        path = context.resolve_path(path_str)
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
