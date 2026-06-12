"""Git and GitHub tools.

Consolidates git_tools.py and github_tools.py.
"""

from __future__ import annotations



# ======================================================================
# From git_tools.py
# ======================================================================


import asyncio
from pathlib import Path

from deepseek_tui.tools.validation import optional_string as _optional_string
from deepseek_tui.tools.validation import require_string as _require_string
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext


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




def _optional_int(input_data: dict[str, object], key: str) -> int | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    return value


# ======================================================================
# From github_tools.py
# ======================================================================


import asyncio
from pathlib import Path

from deepseek_tui.tools.validation import optional_string as _optional_string
from deepseek_tui.tools.validation import require_string as _require_string
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext


class GitHubIssueContextTool(ToolSpec):
    def name(self) -> str:
        return "github_issue_context"

    def description(self) -> str:
        return "Read issue details and comments from GitHub via gh CLI."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "issue_number": {"type": "integer"},
            },
            "required": ["repo", "issue_number"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        repo = _require_string(input_data, "repo")
        issue_number = _require_int(input_data, "issue_number")
        return await _run_gh(
            context.working_directory,
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo,
            "--comments",
        )


class GitHubPrContextTool(ToolSpec):
    def name(self) -> str:
        return "github_pr_context"

    def description(self) -> str:
        return "Read pull request details and comments from GitHub via gh CLI."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "pr_number": {"type": "integer"},
            },
            "required": ["repo", "pr_number"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        repo = _require_string(input_data, "repo")
        pr_number = _require_int(input_data, "pr_number")
        return await _run_gh(
            context.working_directory,
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--comments",
        )


class GitHubCommentTool(ToolSpec):
    def name(self) -> str:
        return "github_comment"

    def description(self) -> str:
        return "Post an issue or pull request comment through gh CLI."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "issue_number": {"type": "integer"},
                "pr_number": {"type": "integer"},
                "body": {"type": "string"},
            },
            "required": ["repo", "body"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.NETWORK, ToolCapability.REQUIRES_APPROVAL]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        repo = _require_string(input_data, "repo")
        body = _require_string(input_data, "body")
        subject, number = _resolve_target(input_data)
        return await _run_gh(
            context.working_directory,
            subject,
            "comment",
            str(number),
            "--repo",
            repo,
            "--body",
            body,
        )


class GitHubCloseTool(ToolSpec):
    def name(self) -> str:
        return "github_close"

    def description(self) -> str:
        return "Close an issue or pull request through gh CLI."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "issue_number": {"type": "integer"},
                "pr_number": {"type": "integer"},
                "comment": {"type": "string"},
            },
            "required": ["repo"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.NETWORK, ToolCapability.REQUIRES_APPROVAL]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        repo = _require_string(input_data, "repo")
        subject, number = _resolve_target(input_data)
        args = [subject, "close", str(number), "--repo", repo]
        comment = _optional_string(input_data, "comment")
        if comment is not None:
            args.extend(["--comment", comment])
        return await _run_gh(context.working_directory, *args)


async def _run_gh(cwd: Path, *args: str) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        "gh",
        *args,
        cwd=str(cwd),
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
            "cwd": str(cwd),
            "args": ["gh", *args],
            "returncode": process.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
        },
    )




def _require_int(input_data: dict[str, object], key: str) -> int:
    value = input_data.get(key)
    if not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    return value


def _resolve_target(input_data: dict[str, object]) -> tuple[str, int]:
    issue_number = input_data.get("issue_number")
    pr_number = input_data.get("pr_number")
    if isinstance(issue_number, int) and pr_number is None:
        return "issue", issue_number
    if isinstance(pr_number, int) and issue_number is None:
        return "pr", pr_number
    raise ToolError("Provide exactly one of issue_number or pr_number")
