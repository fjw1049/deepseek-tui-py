from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


class GrepFilesTool(ToolSpec):
    def name(self) -> str:
        return "grep_files"

    def description(self) -> str:
        return "Search for a text pattern inside files under a directory."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern", "path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        pattern = _require_string(input_data, "pattern")
        root = context.resolve_path(_require_string(input_data, "path"))
        matches = await asyncio.to_thread(_grep_files, root, pattern)
        return ToolResult(
            success=True,
            content="\n".join(matches),
            metadata={"path": str(root), "count": len(matches)},
        )


class FileSearchTool(ToolSpec):
    def name(self) -> str:
        return "file_search"

    def description(self) -> str:
        return "Find files by name pattern under a directory."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern", "path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        pattern = _require_string(input_data, "pattern")
        root = context.resolve_path(_require_string(input_data, "path"))
        matches = await asyncio.to_thread(_file_search, root, pattern)
        return ToolResult(
            success=True,
            content="\n".join(matches),
            metadata={"path": str(root), "count": len(matches)},
        )


def _require_string(input_data: dict[str, object], key: str) -> str:
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _grep_files(root: Path, pattern: str) -> list[str]:
    results: list[str] = []
    for path in _iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                results.append(f"{path}:{line_number}:{line}")
    return results


def _file_search(root: Path, pattern: str) -> list[str]:
    return [str(path) for path in _iter_files(root) if pattern in path.name]
