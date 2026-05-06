from __future__ import annotations

import asyncio
from pathlib import Path

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


class GitStatusTool(ToolSpec):
    def name(self) -> str:
        return "git_status"

    def description(self) -> str:
        return "Show git status for a repository."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        root = _resolve_root(input_data, context)
        return await _run_git(root, "status", "--short", "--branch")


class GitDiffTool(ToolSpec):
    def name(self) -> str:
        return "git_diff"

    def description(self) -> str:
        return "Show git diff output for a repository."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "staged": {"type": "boolean"},
                "revspec": {"type": "string"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        root = _resolve_root(input_data, context)
        args = ["diff"]
        if bool(input_data.get("staged", False)):
            args.append("--cached")
        revspec = _optional_string(input_data, "revspec")
        if revspec is not None:
            args.append(revspec)
        return await _run_git(root, *args)


class GitLogTool(ToolSpec):
    def name(self) -> str:
        return "git_log"

    def description(self) -> str:
        return "Show recent git commits for a repository."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_count": {"type": "integer"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        root = _resolve_root(input_data, context)
        max_count = _optional_int(input_data, "max_count") or 20
        return await _run_git(root, "log", f"--max-count={max_count}", "--oneline")


class GitShowTool(ToolSpec):
    def name(self) -> str:
        return "git_show"

    def description(self) -> str:
        return "Show a git object in a repository."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "object": {"type": "string"},
            },
            "required": ["object"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        root = _resolve_root(input_data, context)
        object_name = _require_string(input_data, "object")
        return await _run_git(root, "show", object_name)


class GitBlameTool(ToolSpec):
    def name(self) -> str:
        return "git_blame"

    def description(self) -> str:
        return "Show git blame information for a file."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "file": {"type": "string"},
                "line_start": {"type": "integer"},
                "line_end": {"type": "integer"},
            },
            "required": ["file"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        root = _resolve_root(input_data, context)
        file_path = _require_string(input_data, "file")
        line_start = _optional_int(input_data, "line_start")
        line_end = _optional_int(input_data, "line_end")
        args = ["blame", "-f"]
        if line_start is not None or line_end is not None:
            if line_start is None or line_end is None:
                raise ToolError("line_start and line_end must be provided together")
            args.extend(["-L", f"{line_start},{line_end}"])
        args.extend(["--", file_path])
        return await _run_git(root, *args)


def _resolve_root(input_data: dict[str, object], context: ToolContext) -> Path:
    path = _optional_string(input_data, "path") or "."
    return context.resolve_path(path)


async def _run_git(root: Path, *args: str) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    stdout_text = stdout.decode("utf-8") if stdout else ""
    stderr_text = stderr.decode("utf-8") if stderr else ""
    content = (stdout_text + stderr_text).strip()
    return ToolResult(
        success=process.returncode == 0,
        content=content,
        metadata={
            "cwd": str(root),
            "args": ["git", *args],
            "returncode": process.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
        },
    )


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


def _optional_int(input_data: dict[str, object], key: str) -> int | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    return value
