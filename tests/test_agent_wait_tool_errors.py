"""Regression tests for agent wait-action parity and tool failure event wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.events import ToolResultEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolError
from deepseek_tui.tools.registry import ToolContext, ToolResult
from deepseek_tui.tools.subagent import (
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
)
from deepseek_tui.tools.subagent import AgentTool


def _snapshot(agent_id: str, *, running: bool) -> SubAgentResult:
    return SubAgentResult(
        agent_id=agent_id,
        agent_type=SubAgentType.EXPLORE,
        assignment=SubAgentAssignment(objective="probe"),
        model="deepseek-v4-pro",
        nickname=None,
        status=SubAgentStatus.running() if running else SubAgentStatus.completed(),
        result=None,
        steps_taken=0,
        duration_ms=0,
    )


@pytest.mark.asyncio
async def test_agent_wait_without_ids_waits_running_agents() -> None:
    manager = MagicMock()
    manager.list_filtered.return_value = [
        _snapshot("agent_running", running=True),
        _snapshot("agent_done", running=False),
    ]
    manager.wait = AsyncMock(return_value=[_snapshot("agent_running", running=False)])

    tool = AgentTool()
    ctx = ToolContext(working_directory="/tmp", subagent_manager=manager)
    result = await tool.execute({"action": "wait", "mode": "all", "timeout_ms": 5000}, ctx)

    assert result.success is True
    manager.wait.assert_awaited_once_with(
        ["agent_running"], mode="all", timeout_ms=30000
    )


@pytest.mark.asyncio
async def test_agent_wait_without_ids_and_no_running_returns_empty() -> None:
    manager = MagicMock()
    manager.list_filtered.return_value = [_snapshot("agent_done", running=False)]
    manager.wait = AsyncMock()

    tool = AgentTool()
    ctx = ToolContext(working_directory="/tmp", subagent_manager=manager)
    result = await tool.execute({"action": "wait", "wait_mode": "all"}, ctx)

    assert result.success is True
    assert result.content == "[]"
    manager.wait.assert_not_called()


@pytest.mark.asyncio
async def test_agent_wait_rejects_invalid_wait_mode() -> None:
    manager = MagicMock()
    tool = AgentTool()
    ctx = ToolContext(working_directory="/tmp", subagent_manager=manager)

    with pytest.raises(ToolError, match="Invalid wait_mode"):
        await tool.execute({"action": "wait", "wait_mode": "bogus"}, ctx)


@pytest.mark.asyncio
async def test_emit_tool_failure_emits_tool_result_event_only() -> None:
    handle = EngineHandle()
    engine = Engine(handle=handle, client=AsyncMock())
    tool_call = ToolCall(id="call_test", name="agent", arguments={"action": "wait", "mode": "all"})

    await engine._emit_tool_failure(tool_call, "agent_ids or agent_id is required")

    event = handle._event_queue.get_nowait()
    assert isinstance(event, ToolResultEvent)
    assert event.success is False
    assert event.tool_call_id == "call_test"
    assert event.content == "agent_ids or agent_id is required"
    assert handle._event_queue.empty()


@pytest.mark.parametrize("with_unattached_goal", [False, True])
@pytest.mark.asyncio
async def test_agent_spawn_returns_success_outside_goal_turn(
    engine_ctx, monkeypatch, with_unattached_goal
) -> None:
    engine, handle = engine_ctx
    if with_unattached_goal:
        engine.goal_service.create("A goal outside this turn")
        engine.tool_context.metadata["goal_turn_id"] = "another-goal"
    manager = engine.tool_context.subagent_manager
    spawn = AsyncMock(return_value=_snapshot("agent_spawned", running=True))
    monkeypatch.setattr(manager, "spawn", spawn)

    results = await engine._execute_tool_calls([
        ToolCall(
            id="spawn", name="agent",
            arguments={"action": "spawn", "agent_type": "explore", "prompt": "map auth"},
        )
    ])

    spawn.assert_awaited_once()
    assert len(results) == 1
    assert not results[0].content[0].is_error
    assert "agent_spawned" in results[0].content[0].content
    events = [event for event in handle.drain_events() if isinstance(event, ToolResultEvent)]
    assert len(events) == 1
    assert events[0].success
    assert events[0].metadata["status"]["kind"] == "running"
    goal = engine.goal_service.snapshot()
    assert goal is None or not goal.evidence


@pytest.mark.parametrize(
    "metadata,tool_success,success,finished",
    [
        ({"status": {"kind": "running"}}, True, True, False),
        ({"status": {"kind": "completed"}}, True, True, True),
        ({"status": {"kind": "failed"}}, True, False, True),
        ({"status": "running"}, True, True, False),
        ({"status": "failed"}, True, False, True),
        ({"status": "error"}, True, False, True),
        ({"status": "cancelled"}, True, True, False),
        ({"status": {"kind": "completed"}, "background": True}, True, True, False),
        ({}, True, True, True),
        ({"status": {"kind": "completed"}}, False, False, True),
    ],
)
@pytest.mark.asyncio
async def test_goal_tool_evidence_handles_subagent_and_process_status(
    engine_ctx, monkeypatch, metadata, tool_success, success, finished
) -> None:
    engine, _ = engine_ctx
    goal = engine.goal_service.create("Inspect the result")
    engine.tool_context.metadata["goal_turn_id"] = goal.goal_id
    monkeypatch.setattr(
        engine, "_execute_single_tool_impl",
        AsyncMock(return_value=ToolResult(
            success=tool_success, content="result collected", metadata=metadata,
        )),
    )

    results = await engine._execute_tool_calls([
        ToolCall(id="collect", name="task_output", arguments={"agent_id": "agent_result"})
    ])

    assert results[0].content[0].is_error is not tool_success
    evidence = engine.goal_service.snapshot().evidence
    assert len(evidence) == 1
    assert evidence[0]["tool_call_id"] == "collect"
    assert evidence[0]["success"] is success
    assert evidence[0]["finished"] is finished
