

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable
from pathlib import Path

from deepseek_tui.tools.validation import require_string as _require_string
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext

logger = logging.getLogger(__name__)


class GrepFilesTool(ToolSpec):
    def name(self) -> str:
        return "grep_files"

    def description(self) -> str:
        return (
            "Search files for a regular expression. ``pattern`` is a Python "
            "regex (use ``\\\\b`` for word boundaries, ``(?i)`` for case-insensitive). "
            "``ignore_case`` toggles case insensitivity without inline flags."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression to match against each line.",
                },
                "path": {"type": "string"},
                "ignore_case": {"type": "boolean", "default": False},
            },
            "required": ["pattern", "path"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        pattern = _require_string(input_data, "pattern")
        root = context.resolve_path(_require_string(input_data, "path"))
        ignore_case = bool(input_data.get("ignore_case", False))
        try:
            flags = re.IGNORECASE if ignore_case else 0
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            logger.warning("grep_files_invalid_regex pattern=%r error=%s", pattern, exc)
            raise ToolError(f"invalid regex pattern: {exc}") from exc
        matches = await asyncio.to_thread(_grep_files, root, compiled)
        logger.info(
            "grep_files pattern=%r root=%s ignore_case=%s match_count=%d",
            pattern,
            root,
            ignore_case,
            len(matches),
        )
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
        logger.info(
            "file_search pattern=%r root=%s match_count=%d",
            pattern,
            root,
            len(matches),
        )
        return ToolResult(
            success=True,
            content="\n".join(matches),
            metadata={"path": str(root), "count": len(matches)},
        )




def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _grep_files(root: Path, pattern: re.Pattern[str]) -> list[str]:
    results: list[str] = []
    for path in _iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                results.append(f"{path}:{line_number}:{line}")
    return results


def _file_search(root: Path, pattern: str) -> list[str]:
    return [str(path) for path in _iter_files(root) if pattern in path.name]
