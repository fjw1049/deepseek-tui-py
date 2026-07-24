"""Utility tools.

Consolidates utility_tools.py.
"""

from __future__ import annotations



import logging
from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import (
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext

logger = logging.getLogger(__name__)


class DiagnosticsTool(ToolSpec):
    def name(self) -> str:
        return "diagnostics"

    def description(self) -> str:
        return "Collect environment diagnostics for debugging."

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        import platform
        import sys

        info = {
            "python": sys.version,
            "platform": platform.platform(),
            "cwd": str(context.working_directory),
        }
        lines = [f"{k}: {v}" for k, v in info.items()]
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata=info,
        )


class ProjectMapTool(ToolSpec):
    def name(self) -> str:
        return "project_map"

    def description(self) -> str:
        return "Generate a directory tree of the project."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        rel_raw = input_data.get("path") or "."
        if not isinstance(rel_raw, str):
            raise ToolError("path must be a string")
        root = context.resolve_path(rel_raw)
        if not root.is_dir():
            raise ToolError(f"Not a directory: {rel_raw}")
        max_depth = input_data.get("max_depth", 3)
        if not isinstance(max_depth, int):
            raise ToolError("max_depth must be an integer")
        lines: list[str] = []
        _walk(root, root, lines, max_depth, 0)
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={"root": str(root), "entries": len(lines)},
        )


def _walk(base: Path, current: Path, lines: list[str], max_depth: int, depth: int) -> None:
    if depth > max_depth:
        return
    indent = "  " * depth
    entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            lines.append(f"{indent}{entry.name}/")
            _walk(base, entry, lines, max_depth, depth + 1)
        else:
            lines.append(f"{indent}{entry.name}")
