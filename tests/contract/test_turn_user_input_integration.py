"""Engine-path user_input: monitor emits SSE and HTTP resolve unblocks future."""

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
from deepseek_tui.engine.events import TurnCompleteEvent, UserInputRequiredEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.registry import ToolContext


@pytest.mark.asyncio
async def test_monitor_turn_user_input_required_event_log(
    runtime_app: object,
) -> None:
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
    questions = [
        {
            "id": "pick",
            "header": "Choose",
            "question": "Continue?",
            "options": [{"label": "Yes", "description": ""}],
        }
    ]

    stub_engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    async def pump() -> None:
        await handle.emit(
            UserInputRequiredEvent(tool_call_id="uinp_monitor", questions=questions)
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
    ui_events = [e for e in events if e.event == "user_input.required"]
    assert len(ui_events) == 1
    payload = ui_events[0].payload
    assert payload["request_id"] == "uinp_monitor"
    assert payload["questions"] == questions


@pytest.mark.asyncio
async def test_user_input_resolve_during_active_turn(
    client: object,
    runtime_app: object,
) -> None:
    """POST /v1/user-inputs resolves EngineHandle future while thread is loaded."""
    from httpx import AsyncClient

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    assert isinstance(client, AsyncClient)

    handle = EngineHandle()
    request_id = "uinp_turn_live"
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    handle.pending_user_inputs[request_id] = future

    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    stub_engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread_id] = _ActiveThreadState(handle, stub_engine, engine_task)

    try:
        r = await client.post(
            f"/v1/user-inputs/{request_id}",
            json={"answers": [{"question_id": "pick", "value": "yes"}]},
        )
        assert r.status_code == 200
        result = await asyncio.wait_for(future, timeout=1.0)
        assert result == {"answers": [{"question_id": "pick", "value": "yes"}]}
    finally:
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread_id, None)
