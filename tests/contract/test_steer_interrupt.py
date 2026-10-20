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
