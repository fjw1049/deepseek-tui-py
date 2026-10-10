from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from deepseek_tui.server.approval import PendingApprovalRecord
from deepseek_tui.server.threads.models import CreateThreadRequest, RuntimeTurnStatus, TurnRecord


@pytest.mark.asyncio
async def test_list_includes_latest_activity_without_opening_thread(client: AsyncClient, runtime_app):
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(CreateThreadRequest(title="Activity test"))
    now = datetime.now(timezone.utc)
    turn = TurnRecord(id="turn_activity", thread_id=thread.id, status=RuntimeTurnStatus.FAILED,
                      input_summary="test", created_at=now, error="failed")
    mgr.store.save_turn(turn)
    thread.latest_turn_id = turn.id
    mgr.store.save_thread(thread)
    bridge = runtime_app.state.approval_bridge
    bridge.register("approval_activity", meta=PendingApprovalRecord(
        thread_id=thread.id, tool_name="write_file", description="Write a file"))
    response = await client.get("/v1/threads")
    assert response.status_code == 200
    row = next(row for row in response.json() if row["id"] == thread.id)
    assert row["latest_turn_status"] == "failed"
    assert row["latest_turn_failed"] is True
    assert row["activity_waiting"] is True
    assert row["activity_at"] == now.isoformat()
    bridge.resolve("approval_activity", True)
    turn.status = RuntimeTurnStatus.IN_PROGRESS
    turn.error = None
    mgr.store.save_turn(turn)
    row = next(row for row in (await client.get("/v1/threads")).json() if row["id"] == thread.id)
    assert row["latest_turn_status"] == "in_progress"
    assert row["latest_turn_failed"] is False
    assert row["activity_waiting"] is False


@pytest.mark.asyncio
async def test_new_thread_has_no_invented_completion(client: AsyncClient, runtime_app):
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(CreateThreadRequest(title="Draft"))
    row = next(row for row in (await client.get("/v1/threads")).json() if row["id"] == thread.id)
    assert "latest_turn_status" not in row
    assert row["activity_waiting"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_turn", ["missing", "corrupt"])
async def test_unreadable_turn_does_not_break_listing(client: AsyncClient, runtime_app, invalid_turn):
    mgr = runtime_app.state.thread_manager
    thread = await mgr.create_thread(CreateThreadRequest(title="Recoverable thread"))
    thread.latest_turn_id = "turn_unreadable"
    mgr.store.save_thread(thread)
    if invalid_turn == "corrupt":
        mgr.store._turn_path(thread.latest_turn_id).write_text("{not json", encoding="utf-8")
    response = await client.get("/v1/threads")
    assert response.status_code == 200
    row = next(row for row in response.json() if row["id"] == thread.id)
    assert "latest_turn_status" not in row
