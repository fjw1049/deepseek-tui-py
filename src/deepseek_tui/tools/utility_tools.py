from __future__ import annotations

import asyncio
from pathlib import Path

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


class ApplyPatchTool(ToolSpec):
    def name(self) -> str:
        return "apply_patch"

    def description(self) -> str:
        return "Apply a unified diff patch to the working directory."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "patch": {"type": "string"},
                "strip": {"type": "integer"},
            },
            "required": ["patch"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        patch = _require_string(input_data, "patch")
        strip = input_data.get("strip", 1)
        if not isinstance(strip, int):
            raise ToolError("strip must be an integer")
        process = await asyncio.create_subprocess_exec(
            "patch",
            f"-p{strip}",
            "--forward",
            cwd=str(context.working_directory),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(patch.encode("utf-8"))
        stdout_text = stdout.decode("utf-8") if stdout else ""
        stderr_text = stderr.decode("utf-8") if stderr else ""
        content = (stdout_text + stderr_text).strip()
        return ToolResult(
            success=process.returncode == 0,
            content=content,
            metadata={"returncode": process.returncode},
        )


class DiagnosticsTool(ToolSpec):
    def name(self) -> str:
        return "diagnostics"

    def description(self) -> str:
        return "Collect environment diagnostics for debugging."

    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
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

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        rel = _optional_string(input_data, "path") or "."
        root = context.resolve_path(rel)
        if not root.is_dir():
            raise ToolError(f"Not a directory: {rel}")
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


def _require_string(input_data: dict[str, object], key: str) -> str:
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _optional_string(input_data: dict[str, object], key: str) -> str | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value
