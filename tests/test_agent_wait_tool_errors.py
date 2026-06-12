"""Regression tests for agent_wait parity and tool failure event wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.events import ToolResultEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolError
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.subagent import (
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
)
from deepseek_tui.tools.subagent import AgentWaitTool


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

    tool = AgentWaitTool()
    ctx = ToolContext(working_directory="/tmp", subagent_manager=manager)
    result = await tool.execute({"mode": "all", "timeout_ms": 5000}, ctx)

    assert result.success is True
    manager.wait.assert_awaited_once_with(
        ["agent_running"], mode="all", timeout_ms=30000
    )


@pytest.mark.asyncio
async def test_agent_wait_without_ids_and_no_running_returns_empty() -> None:
    manager = MagicMock()
    manager.list_filtered.return_value = [_snapshot("agent_done", running=False)]
    manager.wait = AsyncMock()

    tool = AgentWaitTool()
    ctx = ToolContext(working_directory="/tmp", subagent_manager=manager)
    result = await tool.execute({"wait_mode": "all"}, ctx)

    assert result.success is True
    assert result.content == "[]"
    manager.wait.assert_not_called()


@pytest.mark.asyncio
async def test_agent_wait_rejects_invalid_wait_mode() -> None:
    manager = MagicMock()
    tool = AgentWaitTool()
    ctx = ToolContext(working_directory="/tmp", subagent_manager=manager)

    with pytest.raises(ToolError, match="Invalid wait_mode"):
        await tool.execute({"wait_mode": "bogus"}, ctx)


@pytest.mark.asyncio
async def test_emit_tool_failure_emits_tool_result_event_only() -> None:
    handle = EngineHandle()
    engine = Engine(handle=handle, client=AsyncMock())
    tool_call = ToolCall(id="call_test", name="agent_wait", arguments={"mode": "all"})

    await engine._emit_tool_failure(tool_call, "agent_ids or agent_id is required")

    event = handle._event_queue.get_nowait()
    assert isinstance(event, ToolResultEvent)
    assert event.success is False
    assert event.tool_call_id == "call_test"
    assert event.content == "agent_ids or agent_id is required"
    assert handle._event_queue.empty()
