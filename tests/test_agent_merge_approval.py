"""Approval-semantics guards for the merged action-dispatch tools.

Covers the regressions found in review after the Phase 1 merges:
approval fingerprints, category classification, checklist read path,
and the sub-agent approval gate.
"""

from __future__ import annotations

import pytest

from deepseek_tui.tools.approval import (
    ApprovalRequirement,
    build_approval_key,
    classify_tool_category,
)
from deepseek_tui.tools.todo import ChecklistTool


def test_agent_approval_key_separates_actions() -> None:
    spawn = build_approval_key("agent", {"action": "spawn", "prompt": "x"})
    send = build_approval_key("agent", {"action": "send_input", "agent_id": "a1"})
    cancel = build_approval_key("agent", {"action": "cancel", "agent_id": "a1"})
    assert len({spawn, send, cancel}) == 3


def test_agent_approval_key_scopes_by_target_id() -> None:
    cancel_a = build_approval_key("agent", {"action": "cancel", "agent_id": "a1"})
    cancel_b = build_approval_key("agent", {"action": "cancel", "agent_id": "b2"})
    assert cancel_a != cancel_b


def test_agent_category_is_subagent() -> None:
    assert classify_tool_category("agent") == "subagent"
    assert classify_tool_category("agent_resume") == "subagent"


def test_checklist_read_path_is_auto() -> None:
    tool = ChecklistTool()
    assert tool.approval_requirement_for_input({}) is ApprovalRequirement.AUTO
    assert (
        tool.approval_requirement_for_input(
            {"todos": [{"content": "x", "status": "pending"}]}
        )
        is ApprovalRequirement.SUGGEST
    )
    # Legacy alias still counts as a write.
    assert (
        tool.approval_requirement_for_input({"items": [{"content": "x"}]})
        is ApprovalRequirement.SUGGEST
    )


# --- Round 2: per-input read-only / parallel planning ----------------------


def test_agent_is_read_only_for_input() -> None:
    from deepseek_tui.tools.subagent import AgentTool

    tool = AgentTool()
    assert tool.is_read_only_for_input({"action": "list"}) is True
    assert tool.is_read_only_for_input({"action": "result", "agent_id": "a"}) is True
    assert tool.is_read_only_for_input({"action": "wait"}) is True
    assert tool.is_read_only_for_input({"action": "spawn", "prompt": "x"}) is False
    assert tool.is_read_only_for_input({"action": "send_input"}) is False
    assert tool.is_read_only_for_input({"action": "cancel"}) is False


def test_checklist_is_read_only_for_input() -> None:
    tool = ChecklistTool()
    assert tool.is_read_only_for_input({}) is True
    assert tool.is_read_only_for_input({"todos": []}) is False
    assert tool.is_read_only_for_input({"items": []}) is False


def test_plan_requires_approval_honours_input() -> None:
    from deepseek_tui.tools.approval import plan_requires_approval
    from deepseek_tui.tools.subagent import AgentTool

    tool = AgentTool()
    assert plan_requires_approval(tool, "on-request", {"action": "list"}) is False
    assert plan_requires_approval(tool, "on-request", {"action": "spawn"}) is True
    checklist = ChecklistTool()
    assert plan_requires_approval(checklist, "on-request", {}) is False
    assert (
        plan_requires_approval(
            checklist, "on-request", {"todos": [{"content": "x"}]}
        )
        is True
    )


def test_checklist_and_git_categories() -> None:
    assert classify_tool_category("checklist") == "safe"
    assert classify_tool_category("git") == "safe"


# --- Sub-agent approval bridge path (loop.py) ------------------------------


@pytest.mark.asyncio
async def test_subagent_loop_read_action_not_gated() -> None:
    from pathlib import Path

    from deepseek_tui.tools.registry import ToolContext, ToolRegistry
    from deepseek_tui.tools.subagent import AgentTool
    from deepseek_tui.tools.subagent.loop import _execute_subagent_tool

    registry = ToolRegistry()
    registry.register(AgentTool())
    ctx = ToolContext(working_directory=Path.cwd())
    out = await _execute_subagent_tool(
        registry,
        ctx,
        tool_name="agent",
        tool_input={"action": "list"},
        auto_approve=False,
    )
    # AUTO requirement → no approval gate; fails later on the missing
    # SubAgentManager instead of the approval bridge.
    assert "requires approval" not in out


@pytest.mark.asyncio
async def test_subagent_loop_spawn_gated_without_bridge() -> None:
    from pathlib import Path

    from deepseek_tui.tools.registry import ToolContext, ToolRegistry
    from deepseek_tui.tools.subagent import AgentTool
    from deepseek_tui.tools.subagent.loop import _execute_subagent_tool

    registry = ToolRegistry()
    registry.register(AgentTool())
    ctx = ToolContext(working_directory=Path.cwd())
    out = await _execute_subagent_tool(
        registry,
        ctx,
        tool_name="agent",
        tool_input={"action": "spawn", "prompt": "x"},
        auto_approve=False,
    )
    assert "requires approval" in out
