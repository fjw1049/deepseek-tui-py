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


# --- resume parameter (retired agent_resume folded into agent) --------------


def test_agent_resume_approval_key_scopes_by_target_id() -> None:
    key = build_approval_key("agent", {"resume": "a1"})
    assert str(key) == "agent:resume:a1"
    assert build_approval_key("agent", {"resume": "b2"}) != key


def test_legacy_agent_resume_shares_resume_fingerprint() -> None:
    """The retired tool name forwards to agent(resume=...) — one session
    grant must cover both call forms."""
    assert build_approval_key("agent_resume", {"agent_id": "a1"}) == build_approval_key(
        "agent", {"resume": "a1"}
    )


def test_agent_resume_requirement_is_required() -> None:
    from deepseek_tui.tools.subagent import AgentTool

    tool = AgentTool()
    assert (
        tool.approval_requirement_for_input({"resume": "a1"})
        is ApprovalRequirement.REQUIRED
    )
    assert tool.is_read_only_for_input({"resume": "a1"}) is False


def test_agent_resume_not_in_plan_schema() -> None:
    from deepseek_tui.tools.subagent import PLAN_AGENT_ACTIONS, AgentTool

    plan_tool = AgentTool(allowed_actions=PLAN_AGENT_ACTIONS, allow_resume=False)
    schema = plan_tool.input_schema()
    assert "resume" not in schema["properties"]
    assert schema["required"] == ["action"]

    full_tool = AgentTool()
    full_schema = full_tool.input_schema()
    assert "resume" in full_schema["properties"]
    # 'action' is enforced in execute() so 'resume' can be passed alone.
    assert full_schema["required"] == []


@pytest.mark.asyncio
async def test_agent_resume_mutually_exclusive_with_action() -> None:
    from pathlib import Path

    from deepseek_tui.tools.registry import ToolContext, ToolError
    from deepseek_tui.tools.subagent import AgentTool

    ctx = ToolContext(working_directory=Path.cwd())
    with pytest.raises(ToolError, match="mutually exclusive"):
        await AgentTool().execute({"action": "list", "resume": "a1"}, ctx)


@pytest.mark.asyncio
async def test_agent_resume_rejected_when_not_allowed() -> None:
    from pathlib import Path

    from deepseek_tui.tools.registry import ToolContext, ToolError
    from deepseek_tui.tools.subagent import PLAN_AGENT_ACTIONS, AgentTool

    tool = AgentTool(allowed_actions=PLAN_AGENT_ACTIONS, allow_resume=False)
    ctx = ToolContext(working_directory=Path.cwd())
    with pytest.raises(ToolError, match="not available"):
        await tool.execute({"resume": "a1"}, ctx)


@pytest.mark.asyncio
async def test_agent_resume_executes_via_manager() -> None:
    from pathlib import Path

    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.subagent import AgentTool
    from deepseek_tui.tools.subagent.types import (
        SubAgentAssignment,
        SubAgentResult,
        SubAgentStatus,
        SubAgentType,
    )

    class _StubManager:
        def __init__(self) -> None:
            self.resumed: list[str] = []

        async def resume(self, agent_id: str) -> SubAgentResult:
            self.resumed.append(agent_id)
            return SubAgentResult(
                agent_id=agent_id,
                agent_type=SubAgentType.GENERAL,
                assignment=SubAgentAssignment(objective="obj"),
                model="m",
                nickname=None,
                status=SubAgentStatus.running(),
                result=None,
                steps_taken=0,
                duration_ms=0,
            )

    manager = _StubManager()
    ctx = ToolContext(working_directory=Path.cwd(), subagent_manager=manager)  # type: ignore[arg-type]
    result = await AgentTool().execute({"resume": "a1"}, ctx)
    assert result.success is True
    assert result.content == "resumed a1"
    assert result.metadata["agent_id"] == "a1"
    assert manager.resumed == ["a1"]


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
    assert tool.is_read_only_for_input({"action": "wait"}) is True
    assert tool.is_read_only_for_input({"action": "spawn", "prompt": "x"}) is False
    assert tool.is_read_only_for_input({"action": "send_input"}) is False
    # Retired actions are no longer read-path actions (they forward to
    # task_list / task_output / task_stop at the execution layer).
    assert tool.is_read_only_for_input({"action": "list"}) is False
    assert tool.is_read_only_for_input({"action": "result", "agent_id": "a"}) is False
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
    assert plan_requires_approval(tool, "on-request", {"action": "wait"}) is False
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


# --- Shell interact / legacy shell / cron fingerprints ------------------------


def test_shell_interact_fingerprint_is_process_scoped() -> None:
    key_a = build_approval_key(
        "exec_shell", {"process_id": "p1", "input": "y\n"}
    )
    assert str(key_a) == "shell:interact:p1"
    assert key_a != build_approval_key(
        "exec_shell", {"process_id": "p2", "input": "y\n"}
    )
    # Legacy interact name shares the same process-scoped key.
    assert key_a == build_approval_key(
        "exec_shell_interact", {"process_id": "p1", "input": "y\n"}
    )
    # Command execution stays on the command-prefix fingerprint.
    assert key_a != build_approval_key("exec_shell", {"command": "echo hi"})


def test_task_shell_start_normalized_fingerprint_matches_exec_shell() -> None:
    """After legacy normalize, task_shell_start must not use a bare tool key."""
    from deepseek_tui.engine.dispatch import normalize_legacy_tool_call

    name, args = normalize_legacy_tool_call(
        "task_shell_start",
        {"command": "make test", "task_id": "t1", "pty": False},
    )
    assert name == "exec_shell"
    assert build_approval_key(name, args) == build_approval_key(
        "exec_shell",
        {"command": "make test", "background": True, "pty": False},
    )
    # Different commands must not share a session grant.
    assert build_approval_key(name, args) != build_approval_key(
        "exec_shell", {"command": "rm -rf /", "background": True}
    )


def test_cron_legacy_names_share_fingerprints() -> None:
    create_args = {
        "name": "hourly",
        "prompt": "do work",
        "rrule": "FREQ=HOURLY;INTERVAL=1",
    }
    assert build_approval_key("automation_create", create_args) == build_approval_key(
        "cron_create", create_args
    )
    delete_a = build_approval_key("cron_delete", {"automation_id": "a1"})
    assert delete_a == build_approval_key(
        "automation_delete", {"automation_id": "a1"}
    )
    assert delete_a != build_approval_key(
        "cron_delete", {"automation_id": "b2"}
    )


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
        tool_input={"action": "wait"},
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
