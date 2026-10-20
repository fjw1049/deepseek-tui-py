from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads.manager import RuntimeThreadManager


@pytest.mark.asyncio
async def test_activity_stays_true_until_terminal_turn_releases_lease() -> None:
    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager._thread_lease_guard = asyncio.Lock()
    manager._thread_leases = {"thread": object()}
    manager._active_lock = asyncio.Lock()
    manager._active = {}
    manager.store = Mock()
    manager.store.load_thread.return_value = SimpleNamespace(latest_turn_id="turn")
    manager.store.load_turn.return_value = SimpleNamespace(status="interrupted")

    assert await manager.is_thread_turn_active("thread") is True
    manager._thread_leases.clear()
    assert await manager.is_thread_turn_active("thread") is False


def _lease_manager(active_turn=None, status="in_progress") -> RuntimeThreadManager:
    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager._cancel_event = asyncio.Event()
    manager._thread_lease_guard = asyncio.Lock()
    manager._thread_leases = {}
    manager._thread_lease_depth = {}
    manager._thread_lease_owners = {}
    manager._lease_released = {}
    manager._active_lock = asyncio.Lock()
    manager._active = {"thread": SimpleNamespace(active_turn=active_turn)}
    manager.store = Mock()
    manager.store.load_turn.return_value = SimpleNamespace(status=status)
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize("winding_down", [
    None,  # record closed; browser hand-back / publish still hold the thread
    SimpleNamespace(turn_id="old", interrupt_requested=True),  # Stop was requested
])
async def test_new_turn_starts_as_soon_as_a_finished_turn_releases_the_thread(winding_down):
    manager = _lease_manager(active_turn=winding_down)
    old = await manager._claim_new_thread_lease("thread")
    start = asyncio.create_task(manager._claim_new_thread_lease("thread", wait_for_handoff=True))
    await asyncio.sleep(0.05)
    assert not start.done()  # Waits instead of failing with a conflict.
    manager._active["thread"].active_turn = None
    await manager._release_thread_lease("thread", expected=old)
    new = await asyncio.wait_for(start, 1)
    assert manager._thread_leases["thread"] is new
    await manager._release_thread_lease("thread", expected=new)


@pytest.mark.asyncio
async def test_a_running_turn_still_rejects_a_new_turn_immediately():
    from deepseek_tui.server.threads.manager import TurnConflictError

    manager = _lease_manager(SimpleNamespace(turn_id="live", interrupt_requested=False))
    old = await manager._claim_new_thread_lease("thread")
    try:
        with pytest.raises(TurnConflictError, match="active operation"):
            await asyncio.wait_for(
                manager._claim_new_thread_lease("thread", wait_for_handoff=True), 0.5
            )
        # Callers that do not wait keep the old fail-fast behavior.
        manager._active["thread"].active_turn = None
        with pytest.raises(TurnConflictError):
            await asyncio.wait_for(manager._claim_new_thread_lease("thread"), 0.5)
    finally:
        await manager._release_thread_lease("thread", expected=old)


@pytest.mark.asyncio
async def test_a_stuck_teardown_ends_the_wait_with_a_conflict(monkeypatch):
    from deepseek_tui.server.threads import manager as manager_module

    monkeypatch.setattr(manager_module, "LEASE_HANDOFF_WAIT_SECONDS", 0.1)
    manager = _lease_manager()
    old = await manager._claim_new_thread_lease("thread")
    try:
        with pytest.raises(manager_module.TurnConflictError):
            await asyncio.wait_for(
                manager._claim_new_thread_lease("thread", wait_for_handoff=True), 1
            )
    finally:
        await manager._release_thread_lease("thread", expected=old)


@pytest.mark.asyncio
async def test_interrupt_unknown_turn(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    r = await client.post(f"/v1/threads/{thread_id}/turns/not-a-turn/interrupt")
    assert r.status_code in {404, 409, 422}


@pytest.mark.asyncio
async def test_steer_unknown_turn(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    r = await client.post(
        f"/v1/threads/{thread_id}/turns/not-a-turn/steer",
        json={"prompt": "Please prioritize this message."},
    )
    assert r.status_code in {404, 409, 422}
