from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_fork_thread(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    fork = await client.post(f"/v1/threads/{thread_id}/fork")
    assert fork.status_code == 201
    forked = fork.json()
    assert forked["id"] != thread_id
    assert forked["id"].startswith("thr_")
