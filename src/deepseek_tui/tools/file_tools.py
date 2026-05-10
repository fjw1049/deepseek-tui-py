from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

logger = logging.getLogger(__name__)


class ReadFileTool(ToolSpec):
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "Read a UTF-8 text file from disk."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        path = context.resolve_path(_require_string(input_data, "path"))
        content = await _read_text(path)
        logger.info("read_file path=%s bytes=%d", path, len(content))
        return ToolResult(success=True, content=content, metadata={"path": str(path)})


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
    """Replace an exact string in a UTF-8 text file.

    Schema mirrors Rust ``crates/tui/src/tools/file.rs:280-340`` keys ``search``
    and ``replace``. Legacy ``old_string`` / ``new_string`` are accepted as
    aliases for backward compatibility. Behavior diverges from Rust on one
    point: Python requires ``search`` to occur exactly once (safety guard),
    while Rust replaces all occurrences. Tracked in HANDOVER as a partial
    parity entry — the schema gap is closed; the multi-occurrence semantic
    gap remains.
    """

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "Replace an exact string in a UTF-8 text file. "
            "Use 'search' for the text to find and 'replace' for its replacement. "
            "The search string must occur exactly once."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "search": {"type": "string", "description": "Text to find (must be unique)."},
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
        content = await _read_text(path)
        matches = content.count(search)
        if matches == 0:
            logger.warning("edit_file_no_match path=%s search_len=%d", path, len(search))
            raise ToolError("search string not found")
        if matches > 1:
            logger.warning(
                "edit_file_not_unique path=%s search_len=%d matches=%d",
                path,
                len(search),
                matches,
            )
            raise ToolError("search string is not unique")
        updated = content.replace(search, replace)
        await _write_text(path, updated)
        logger.info(
            "edit_file path=%s search_len=%d replace_len=%d",
            path,
            len(search),
            len(replace),
        )
        return ToolResult(success=True, content="ok", metadata={"path": str(path)})


class ListDirTool(ToolSpec):
    def name(self) -> str:
        return "list_dir"

    def description(self) -> str:
        return "List directory entries from disk."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        path = context.resolve_path(_require_string(input_data, "path"))
        entries = await _list_dir(path)
        return ToolResult(
            success=True,
            content="\n".join(entries),
            metadata={"path": str(path), "count": len(entries)},
        )


def _require_string(input_data: dict[str, object], key: str) -> str:
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _require_string_with_alias(
    input_data: dict[str, object], primary: str, alias: str
) -> str:
    """Accept primary key, fall back to alias (for schema migration).

    Used by ``edit_file`` to accept both Rust-parity ``search``/``replace``
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


async def _read_text(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")


async def _write_text(path: Path, content: str) -> None:
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")


async def _list_dir(path: Path) -> list[str]:
    entries = await asyncio.to_thread(lambda: sorted(item.name for item in path.iterdir()))
    return entries
