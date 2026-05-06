from __future__ import annotations

import asyncio
from pathlib import Path

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


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
        return ToolResult(success=True, content="ok", metadata={"path": str(path)})


class EditFileTool(ToolSpec):
    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return "Replace an exact string in a UTF-8 text file."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        path = context.resolve_path(_require_string(input_data, "path"))
        old_string = _require_string(input_data, "old_string")
        new_string = _require_string(input_data, "new_string")
        content = await _read_text(path)
        matches = content.count(old_string)
        if matches == 0:
            raise ToolError("old_string not found")
        if matches > 1:
            raise ToolError("old_string is not unique")
        updated = content.replace(old_string, new_string)
        await _write_text(path, updated)
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


async def _read_text(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")


async def _write_text(path: Path, content: str) -> None:
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")


async def _list_dir(path: Path) -> list[str]:
    entries = await asyncio.to_thread(lambda: sorted(item.name for item in path.iterdir()))
    return entries
