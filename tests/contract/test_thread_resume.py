"""POST /v1/threads/{id}/resume contract."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_resume_thread_returns_detail(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={})
    thread_id = create.json()["id"]
    r = await client.post(f"/v1/threads/{thread_id}/resume")
    assert r.status_code == 200
    body = r.json()
    assert body["thread"]["id"] == thread_id
    assert isinstance(body.get("items"), list)


@pytest.mark.asyncio
async def test_resume_unknown_thread(client: AsyncClient) -> None:
    r = await client.post("/v1/threads/thr_nonexistent/resume")
    assert r.status_code == 404
