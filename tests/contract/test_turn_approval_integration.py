"""on-request approval: SSE notification + HttpApprovalHandler bridge."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from deepseek_tui.app_server.runtime_api.approval_bridge import HttpApprovalHandler
from deepseek_tui.app_server.runtime_threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnRecord,
)
from deepseek_tui.app_server.thread_manager import _ActiveThreadState, _ActiveTurnState
from deepseek_tui.engine.events import ApprovalRequiredEvent, TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.execpolicy.models import (
    ApprovalDecision,
    ApprovalRequest,
    RiskLevel,
    ToolCategory,
)
from deepseek_tui.tools.context import ToolContext


@pytest.mark.asyncio
async def test_monitor_turn_emits_approval_required_sse(
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
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)
        manager._active[thread.id].active_turn = _ActiveTurnState(
            turn_id=turn_id, auto_approve=False
        )

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

    await asyncio.gather(pump(), manager._monitor_turn(thread.id, turn_id, handle))

    approval_events = [
        e for e in manager.events_since(thread.id, 0) if e.event == "approval.required"
    ]
    assert len(approval_events) == 1
    assert approval_events[0].payload["approval_id"] == approval_id

    engine_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await engine_task
    async with manager._active_lock:
        manager._active.pop(thread.id, None)


@pytest.mark.asyncio
async def test_http_approval_handler_and_post_allow(
    client: AsyncClient,
    runtime_app: object,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    bridge = manager._approval_bridge
    assert bridge is not None
    handler = HttpApprovalHandler(bridge)

    approval_id = "appr_http_e2e"
    request = ApprovalRequest(
        tool_name="bash",
        risk_level=RiskLevel.MEDIUM,
        category=ToolCategory.CODE_EXEC,
        reason="Run `ls`",
    )

    async def wait_and_post() -> None:
        await asyncio.sleep(0.05)
        r = await client.post(
            f"/v1/approvals/{approval_id}",
            json={"decision": "allow", "remember": False},
        )
        assert r.status_code == 200

    waiter = asyncio.create_task(handler.request_approval(approval_id, request))
    poster = asyncio.create_task(wait_and_post())
    decision = await asyncio.wait_for(waiter, timeout=3.0)
    await poster
    assert decision is ApprovalDecision.APPROVED
