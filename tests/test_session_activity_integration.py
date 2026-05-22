"""Integration tests for session activity + subagent turn handoff (#756).

These tests do NOT call the live API and do NOT auto-start the background
activity coordinator (see ``Engine.run``). Coordinator is started only
when a test explicitly needs mailbox draining.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.engine.events import (
    SessionActivityEvent,
    SubAgentMailboxEvent,
)
from deepseek_tui.tools.subagent.completion import SubAgentCompletion
from deepseek_tui.tools.subagent import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentRuntime,
    SubAgentType,
)
from deepseek_tui.tools.subagent.mailbox import MailboxMessage, MailboxMessageKind
from deepseek_tui.tools.subagent_tools import AgentSpawnTool
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.task_manager import NewTaskRequest


def test_subagent_tool_round_trip_chat_messages() -> None:
    """Sub-agent loops must emit assistant tool_calls before tool results."""
    from deepseek_tui.client.chat_messages import build_chat_messages
    from deepseek_tui.protocol.messages import Message, ToolUseBlock

    messages = [
        Message.user("read scratch/probe.txt"),
        Message.assistant("I'll read the file."),
        Message.assistant_with_tools(
            [ToolUseBlock(id="call_1", name="read_file", input={"path": "scratch/probe.txt"})]
        ),
        Message.tool_result("call_1", "hello", is_error=False),
    ]
    api_messages = build_chat_messages(messages, model="deepseek-v4-pro")
    roles = [m["role"] for m in api_messages]
    assert roles == ["user", "assistant", "assistant", "tool"]
    assert api_messages[-2]["tool_calls"][0]["id"] == "call_1"
    assert api_messages[-1]["tool_call_id"] == "call_1"


@pytest.mark.asyncio
async def test_mailbox_drained_to_subagent_mailbox_events(
    engine_ctx: tuple,
) -> None:
    engine, handle = engine_ctx
    mailbox = engine.tool_runtime.mailbox
    assert mailbox is not None

    engine._activity_coordinator.start()
    try:
        mailbox.send(MailboxMessage.started("agent_x", "explore"))
        await asyncio.sleep(0.5)
    finally:
        await engine._activity_coordinator.stop()

    events = handle.drain_events()
    mailbox_events = [e for e in events if isinstance(e, SubAgentMailboxEvent)]
    assert len(mailbox_events) >= 1
    assert mailbox_events[0].message.kind is MailboxMessageKind.STARTED


@pytest.mark.asyncio
async def test_subagent_completion_sink_enqueued(engine_ctx: tuple) -> None:
    engine, _handle = engine_ctx
    manager = engine.tool_context.subagent_manager
    assert manager is not None

    async def _fast_executor(agent, cancel):  # noqa: ANN001
        return "done from child"

    manager._executor = _fast_executor  # noqa: SLF001

    await manager.spawn(
        SpawnRequest(
            prompt="hi",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="hi"),
            parent_depth=0,
        )
    )
    deadline = time.monotonic() + 3.0
    comps: list = []
    while time.monotonic() < deadline:
        comps = engine._drain_subagent_completions()
        if comps:
            break
        await asyncio.sleep(0.05)
    assert len(comps) >= 1
    assert "<deepseek:subagent.done>" in comps[0].payload


@pytest.mark.asyncio
async def test_failed_subagent_notifies_parent_completion(engine_ctx: tuple) -> None:
    engine, _handle = engine_ctx
    manager = engine.tool_context.subagent_manager
    assert manager is not None

    async def _fail_executor(agent, cancel):  # noqa: ANN001
        raise RuntimeError("subagent boom")

    manager._executor = _fail_executor  # noqa: SLF001

    await manager.spawn(
        SpawnRequest(
            prompt="hi",
            agent_type=SubAgentType.EXPLORE,
            assignment=SubAgentAssignment(objective="hi"),
            parent_depth=0,
        )
    )
    deadline = time.monotonic() + 3.0
    comps: list = []
    while time.monotonic() < deadline:
        comps = engine._drain_subagent_completions()
        if comps:
            break
        await asyncio.sleep(0.05)
    assert len(comps) >= 1
    assert "failed" in comps[0].payload


@pytest.mark.asyncio
async def test_turn_handoff_injects_completion_messages(engine_ctx: tuple) -> None:
    engine, _handle = engine_ctx
    engine._enqueue_subagent_completion(
        SubAgentCompletion(
            agent_id="agent_test01",
            payload=(
                "summary line\n"
                '<deepseek:subagent.done>{"agent_id":"agent_test01"}'
                "</deepseek:subagent.done>"
            ),
        )
    )
    messages = []
    injected = await engine._handle_subagent_turn_handoff(messages)
    assert injected is True
    assert len(messages) == 1
    assert "subagent.done" in str(messages[0].content)


@pytest.mark.asyncio
async def test_task_running_count_in_session_activity(engine_ctx: tuple) -> None:
    engine, handle = engine_ctx
    mgr = engine.tool_context.task_manager
    assert mgr is not None

    async def _stub(task, cancel):  # noqa: ANN001
        from deepseek_tui.tools.task_manager import TaskExecutionResult

        await asyncio.sleep(0.1)
        return TaskExecutionResult(summary="ok")

    mgr._executor = _stub  # noqa: SLF001

    await mgr.add_task(NewTaskRequest(prompt="quick", auto_approve=True))
    assert mgr.running_count() >= 1

    engine._activity_coordinator.start()
    try:
        await asyncio.sleep(0.5)
    finally:
        await engine._activity_coordinator.stop()

    activity = [
        e for e in handle.drain_events() if isinstance(e, SessionActivityEvent)
    ]
    assert any(e.running_tasks >= 1 for e in activity)


@pytest.mark.asyncio
async def test_engine_attaches_subagent_loop_runtime(engine_ctx: tuple) -> None:
    engine, _handle = engine_ctx
    mgr = engine.tool_context.subagent_manager
    assert mgr is not None
    rt = mgr.loop_runtime
    assert rt is not None
    assert rt.manager is mgr
    assert rt.spawn_depth == 0


@pytest.mark.asyncio
async def test_spawn_depth_rejected_at_tool_entry(
    engine_ctx: tuple, isolated_config: Config
) -> None:
    engine, _handle = engine_ctx
    mgr = engine.tool_context.subagent_manager
    assert mgr is not None
    rt = mgr.loop_runtime
    assert rt is not None
    at_max = SubAgentRuntime(
        manager=mgr,
        client=engine.client,
        model=engine.default_model,
        config=isolated_config,
        workspace=engine.tool_context.working_directory,
        spawn_depth=3,
        max_spawn_depth=3,
    )
    ctx = ToolContext(
        working_directory=engine.tool_context.working_directory,
        subagent_manager=mgr,
        metadata={"subagent_depth": 3, "subagent_runtime": at_max},
    )
    tool = AgentSpawnTool()
    from deepseek_tui.tools.base import ToolError

    with pytest.raises(ToolError, match="depth limit"):
        await tool.execute({"prompt": "nested", "type": "explore"}, ctx)
