from __future__ import annotations

import asyncio
from pathlib import Path

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


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
