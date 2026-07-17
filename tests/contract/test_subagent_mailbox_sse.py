"""subagent.mailbox SSE contract."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from datetime import datetime, timezone

from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnRecord,
)
from deepseek_tui.server.threads import _ActiveThreadState
from deepseek_tui.engine.events import SubAgentMailboxEvent, TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.subagent import MailboxMessage


@pytest.mark.asyncio
async def test_monitor_turn_emits_subagent_mailbox(runtime_app: object) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="test",
            created_at=now,
            started_at=now,
        )
    )

    stub_engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    msg = MailboxMessage.started("agent_sub_1", "general")

    async def pump() -> None:
        await handle.emit(SubAgentMailboxEvent(seq=1, message=msg))
        await handle.emit(
            SubAgentMailboxEvent(
                seq=2,
                message=MailboxMessage.progress("agent_sub_1", "reading files"),
            )
        )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = manager.events_since(thread.id, 0)
    mailbox_events = [e for e in events if e.event == "subagent.mailbox"]
    assert len(mailbox_events) == 2
    assert mailbox_events[0].payload["message"]["kind"] == "started"
    assert mailbox_events[0].payload["message"]["agent_id"] == "agent_sub_1"
    assert mailbox_events[1].payload["message"]["status"] == "reading files"


@pytest.mark.asyncio
async def test_monitor_turn_mailbox_payload_includes_tool_call_id(
    runtime_app: object,
) -> None:
    """Parallel same-name calls share a round ``step`` number, so the payload
    must carry the provider ``tool_call_id`` for the UI to key steps per call."""
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="test",
            created_at=now,
            started_at=now,
        )
    )

    stub_engine = SimpleNamespace(
        tool_context=ToolContext(working_directory=manager.workspace)
    )
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    async def pump() -> None:
        await handle.emit(
            SubAgentMailboxEvent(
                seq=1,
                message=MailboxMessage.tool_call_started(
                    "agent_sub_1", "read_file", 3, tool_call_id="call_a"
                ),
            )
        )
        await handle.emit(
            SubAgentMailboxEvent(
                seq=2,
                message=MailboxMessage.tool_call_completed(
                    "agent_sub_1", "read_file", 3, True, tool_call_id="call_a"
                ),
            )
        )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = manager.events_since(thread.id, 0)
    mailbox_events = [e for e in events if e.event == "subagent.mailbox"]
    assert [
        e.payload["message"]["tool_call_id"] for e in mailbox_events
    ] == ["call_a", "call_a"]


@pytest.mark.asyncio
async def test_monitor_turn_drops_foreign_subagent(runtime_app: object) -> None:
    """Leftover sub-agents from a prior turn must not leak into the next turn.

    Turns are serial per thread, so any agent already tracked when a turn
    starts was spawned by an earlier turn. If such an orphan keeps emitting,
    the new turn's monitor must drop its envelopes (otherwise a stray card
    with a lost ``agent_type`` appears). A freshly spawned agent must still
    pass through.
    """
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="test",
            created_at=now,
            started_at=now,
        )
    )

    fake_manager = SimpleNamespace(
        mailbox=None,
        known_agent_ids=lambda: {"agent_prev"},
    )
    stub_engine = SimpleNamespace(
        tool_context=ToolContext(
            working_directory=manager.workspace,
            subagent_manager=fake_manager,
        )
    )
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    async def pump() -> None:
        # Leftover orphan from a prior turn — already known to the manager.
        await handle.emit(
            SubAgentMailboxEvent(
                seq=1, message=MailboxMessage.completed("agent_prev", "leftover")
            )
        )
        # Freshly spawned agent for THIS turn.
        await handle.emit(
            SubAgentMailboxEvent(
                seq=2, message=MailboxMessage.started("agent_new", "explore")
            )
        )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = manager.events_since(thread.id, 0)
    mailbox_events = [e for e in events if e.event == "subagent.mailbox"]
    agent_ids = {e.payload["message"]["agent_id"] for e in mailbox_events}
    assert "agent_prev" not in agent_ids
    assert "agent_new" in agent_ids


@pytest.mark.asyncio
async def test_cancel_orphan_subagents_cancels_only_running(runtime_app: object) -> None:
    """At turn close, still-running sub-agents are cancelled; terminal ones are left."""
    from deepseek_tui.tools.subagent import SubAgentStatusKind

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    cancelled: list[str] = []
    running = SimpleNamespace(status=SimpleNamespace(kind=SubAgentStatusKind.RUNNING))
    done = SimpleNamespace(status=SimpleNamespace(kind=SubAgentStatusKind.COMPLETED))

    async def _get_result(agent_id: str) -> object:
        return running if agent_id == "agent_running" else done

    async def _cancel(agent_id: str) -> None:
        cancelled.append(agent_id)

    fake_manager = SimpleNamespace(get_result=_get_result, cancel=_cancel)
    stub_engine = SimpleNamespace(
        tool_context=ToolContext(
            working_directory=manager.workspace,
            subagent_manager=fake_manager,
        )
    )

    await manager._cancel_orphan_subagents(
        "thread_x", "turn_x", stub_engine, {"agent_running", "agent_done"}
    )

    assert cancelled == ["agent_running"]


@pytest.mark.asyncio
async def test_monitor_turn_reconciles_dropped_terminal(runtime_app: object) -> None:
    """A dropped live ``completed`` envelope must still converge the card.

    Simulates ``handle.try_emit`` discarding the terminal envelope under load:
    only ``started`` arrives live, yet the manager snapshot is ``completed``.
    At turn close ``_reconcile_subagent_cards`` re-asserts the terminal state so
    the card never stays stuck at "running".
    """
    from deepseek_tui.tools.subagent import SubAgentStatusKind

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="test",
            created_at=now,
            started_at=now,
        )
    )

    snap = SimpleNamespace(
        status=SimpleNamespace(kind=SubAgentStatusKind.COMPLETED, message=None),
        result="测试套件 649 个用例，覆盖率良好。",
    )

    async def _get_result(agent_id: str) -> object:
        return snap

    fake_manager = SimpleNamespace(mailbox=None, get_result=_get_result)
    stub_engine = SimpleNamespace(
        tool_context=ToolContext(
            working_directory=manager.workspace,
            subagent_manager=fake_manager,
        )
    )
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    async def pump() -> None:
        await handle.emit(
            SubAgentMailboxEvent(
                seq=1, message=MailboxMessage.started("agent_drop", "explore")
            )
        )
        # The 'completed' envelope is intentionally NOT emitted (dropped live).
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = manager.events_since(thread.id, 0)
    mailbox_events = [e for e in events if e.event == "subagent.mailbox"]
    kinds = [e.payload["message"]["kind"] for e in mailbox_events]
    assert "started" in kinds
    assert "completed" in kinds
    completed = next(
        e for e in mailbox_events if e.payload["message"]["kind"] == "completed"
    )
    assert completed.payload["message"]["agent_id"] == "agent_drop"
    assert "649" in completed.payload["message"]["summary"]


@pytest.mark.asyncio
async def test_monitor_turn_reconciles_on_cancel(runtime_app: object) -> None:
    """Interrupt must flush/reconcile terminal mailbox — same as TurnComplete.

    Regression: TurnCancelledEvent used to break out of ``_monitor_turn`` without
    calling ``_reconcile_subagent_cards``, leaving cancelled workers stuck at
    ``running`` in the UI (and blocking the composer via busy detection).
    """
    from deepseek_tui.engine.events import TurnCancelledEvent
    from deepseek_tui.tools.subagent import SubAgentStatusKind

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="test",
            created_at=now,
            started_at=now,
        )
    )

    snap = SimpleNamespace(
        status=SimpleNamespace(kind=SubAgentStatusKind.CANCELLED, message=None),
        result=None,
    )

    async def _get_result(agent_id: str) -> object:
        return snap

    fake_manager = SimpleNamespace(mailbox=None, get_result=_get_result)
    stub_engine = SimpleNamespace(
        tool_context=ToolContext(
            working_directory=manager.workspace,
            subagent_manager=fake_manager,
        )
    )
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    async def pump() -> None:
        await handle.emit(
            SubAgentMailboxEvent(
                seq=1, message=MailboxMessage.started("agent_stuck", "general")
            )
        )
        await handle.emit(TurnCancelledEvent(reason="user_cancelled"))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    events = manager.events_since(thread.id, 0)
    mailbox_events = [e for e in events if e.event == "subagent.mailbox"]
    kinds = [e.payload["message"]["kind"] for e in mailbox_events]
    assert "started" in kinds
    assert "cancelled" in kinds
    cancelled = next(
        e for e in mailbox_events if e.payload["message"]["kind"] == "cancelled"
    )
    assert cancelled.payload["message"]["agent_id"] == "agent_stuck"
