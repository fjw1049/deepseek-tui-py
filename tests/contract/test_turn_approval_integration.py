"""on-request approval: monitor SSE + ApprovalBridge HTTP resolve."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from datetime import datetime, timezone

from deepseek_tui.app_server.runtime_threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnRecord,
)
from deepseek_tui.app_server.thread_manager import _ActiveThreadState, _ActiveTurnState
from deepseek_tui.engine.events import ApprovalRequiredEvent, TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.execpolicy.models import ApprovalRequest, RiskLevel, ToolCategory
from deepseek_tui.tools.context import ToolContext


@pytest.mark.asyncio
async def test_monitor_turn_approval_required_and_bridge_resolve(
    client: AsyncClient,
    runtime_app: object,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest(auto_approve=False))
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
    approval_id = "appr_monitor_e2e"

    stub_engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        state = _ActiveThreadState(handle, stub_engine, engine_task)
        state.active_turn = _ActiveTurnState(turn_id=turn_id, auto_approve=False)
        manager._active[thread.id] = state

    async def pump() -> None:
        await handle.emit(
            ApprovalRequiredEvent(
                tool_call_id=approval_id,
                request=ApprovalRequest(
                    tool_name="bash",
                    risk_level=RiskLevel.MEDIUM,
                    category=ToolCategory.CODE_EXEC,
                    reason="Run `ls` in workspace",
                ),
            )
        )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    async def run_monitor() -> None:
        await manager._monitor_turn(thread.id, turn_id, handle)

    monitor_task = asyncio.create_task(run_monitor())
    pump_task = asyncio.create_task(pump())

    for _ in range(50):
        await asyncio.sleep(0.02)
        events = manager.events_since(thread.id, 0)
        if any(e.event == "approval.required" for e in events):
            break
    else:
        await pump_task
        await monitor_task
        pytest.fail("approval.required SSE was not emitted")

    approval_events = [e for e in manager.events_since(thread.id, 0) if e.event == "approval.required"]
    assert approval_events[-1].payload["approval_id"] == approval_id

    r = await client.post(
        f"/v1/approvals/{approval_id}",
        json={"decision": "allow", "remember": False},
    )
    assert r.status_code == 200
    assert r.json()["decision"] == "allow"

    await asyncio.wait_for(monitor_task, timeout=3.0)
    await pump_task

    engine_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await engine_task
    async with manager._active_lock:
        manager._active.pop(thread.id, None)
