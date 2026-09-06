import asyncio
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.server.approval import HttpApprovalHandler
from deepseek_tui.tools.approval import ApprovalDecision, ApprovalRequest, RiskLevel, ToolCategory


def request():
    return ApprovalRequest(
        tool_name="exec_shell",
        risk_level=RiskLevel.MEDIUM,
        category=ToolCategory.CODE_EXEC,
        reason="Run command",
    )


@pytest.mark.parametrize("crash", [False, True])
async def test_monitor_exit_cleans_only_its_turn_and_old_http_answer_fails(
    runtime_app, client, monkeypatch, crash
):
    manager = runtime_app.state.thread_manager
    bridge = runtime_app.state.approval_bridge
    old = HttpApprovalHandler(bridge, thread_id="thread", get_turn_id=lambda: "old")
    new = HttpApprovalHandler(bridge, thread_id="thread", get_turn_id=lambda: "new")
    reqs = [request(), request()]
    tasks = [
        asyncio.create_task(handler.request_approval("call", req))
        for handler, req in zip([old, new], reqs, strict=True)
    ]
    try:
        await asyncio.sleep(0)
        monkeypatch.setattr(
            manager,
            "_monitor_turn",
            AsyncMock(side_effect=RuntimeError("monitor failed") if crash else None),
        )
        monkeypatch.setattr(manager, "_finalize_turn_after_monitor_crash", AsyncMock())
        await manager._monitor_turn_safe("thread", "old", None, "agent")
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        response = await client.post(
            f"/v1/approvals/{reqs[0].approval_id}", json={"decision": "allow"}
        )
        assert response.status_code == 404
        response = await client.get("/v1/approvals/pending?thread_id=thread")
        assert [row["approval_id"] for row in response.json()] == [reqs[1].approval_id]
        response = await client.post(
            f"/v1/approvals/{reqs[1].approval_id}", json={"decision": "allow", "remember": True}
        )
        assert response.status_code == 200
        assert await tasks[1] is ApprovalDecision.APPROVED_SESSION
        assert not bridge._pending and not bridge._meta and not bridge._remember
    finally:
        bridge.cancel_all()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_unload_cleans_pending_even_when_engine_already_gone(runtime_app):
    manager = runtime_app.state.thread_manager
    bridge = runtime_app.state.approval_bridge
    handler = HttpApprovalHandler(bridge, thread_id="gone")
    task = asyncio.create_task(handler.request_approval("call", request()))
    await asyncio.sleep(0)
    await manager._evict_active_thread("gone")
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bridge.list_pending() == []
