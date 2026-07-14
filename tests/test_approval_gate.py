"""Approval gate — needs_tool_approval_prompt / plan_requires_approval (design §11.1)."""

from __future__ import annotations

import pytest

from deepseek_tui.engine.dispatch import should_parallelize_tool_batch, ToolExecutionPlan
from deepseek_tui.tools.approval import (
    needs_mcp_approval_prompt,
    needs_tool_approval_prompt,
    plan_requires_approval,
    should_block_tool_on_never,
)
from deepseek_tui.tools.file import ReadFileTool, WriteFileTool
from deepseek_tui.tools.shell import ExecShellTool
from deepseek_tui.tools.subagent import AgentSpawnTool
from deepseek_tui.tools.web import FetchUrlTool, WebSearchTool


@pytest.mark.parametrize(
    ("policy", "tool", "expected"),
    [
        ("auto", WriteFileTool(), False),  # G-01
        ("on-request", ReadFileTool(), False),  # G-02
        ("on-request", WriteFileTool(), True),  # G-03
        ("on-request", ExecShellTool(), True),  # G-04
        ("on-request", FetchUrlTool(), False),  # G-05
        ("on-request", WebSearchTool(), False),  # G-06
        ("on-request", AgentSpawnTool(), True),  # G-07
        ("never", WriteFileTool(), False),  # G-08 prompt
        ("never", ReadFileTool(), False),  # G-09
        ("suggest", WriteFileTool(), True),  # G-12
        ("untrusted", WriteFileTool(), True),  # G-13
    ],
)
def test_needs_tool_approval_prompt(policy: str, tool: object, expected: bool) -> None:
    assert needs_tool_approval_prompt(tool, policy) is expected  # type: ignore[arg-type]


def test_needs_tool_approval_prompt_never_blocks_without_prompt() -> None:
    tool = WriteFileTool()
    assert needs_tool_approval_prompt(tool, "never") is False
    assert should_block_tool_on_never(tool, "never") is True


@pytest.mark.parametrize(
    ("name", "policy", "expected"),
    [
        ("list_mcp_tools", "on-request", False),
        ("mcp_linear_save_issue", "on-request", True),
        ("mcp_foo_bar", "on-request", True),
        ("mcp_foo_bar", "auto", False),
    ],
)
def test_needs_mcp_approval_prompt(name: str, policy: str, expected: bool) -> None:
    assert needs_mcp_approval_prompt(name, policy) is expected


def test_plan_requires_approval_write_blocks_parallel_batch() -> None:
    policy = "on-request"
    plans = [
        ToolExecutionPlan(
            index=0,
            id="a",
            name="read_file",
            input={},
            read_only=True,
            supports_parallel=True,
            approval_required=plan_requires_approval(ReadFileTool(), policy),
        ),
        ToolExecutionPlan(
            index=1,
            id="b",
            name="write_file",
            input={},
            read_only=False,
            supports_parallel=False,
            approval_required=plan_requires_approval(WriteFileTool(), policy),
        ),
    ]
    assert should_parallelize_tool_batch(plans) is False


def test_plan_parallel_read_only_only() -> None:
    policy = "on-request"
    plans = [
        ToolExecutionPlan(
            index=0,
            id="a",
            name="read_file",
            input={},
            read_only=True,
            supports_parallel=True,
            approval_required=plan_requires_approval(ReadFileTool(), policy),
        ),
        ToolExecutionPlan(
            index=1,
            id="b",
            name="read_file",
            input={},
            read_only=True,
            supports_parallel=True,
            approval_required=plan_requires_approval(ReadFileTool(), policy),
        ),
    ]
    assert should_parallelize_tool_batch(plans) is True


def test_plan_requires_approval_subagent_blocks_parallel() -> None:
    policy = "on-request"
    plans = [
        ToolExecutionPlan(
            index=0,
            id="a",
            name="read_file",
            input={},
            read_only=True,
            supports_parallel=True,
            approval_required=plan_requires_approval(ReadFileTool(), policy),
        ),
        ToolExecutionPlan(
            index=1,
            id="b",
            name="agent_spawn",
            input={},
            read_only=False,
            supports_parallel=False,
            approval_required=plan_requires_approval(AgentSpawnTool(), policy),
        ),
    ]
    assert should_parallelize_tool_batch(plans) is False
