from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_threads_crud(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={"model": "deepseek-chat"})
    assert create.status_code == 201
    thread = create.json()
    assert isinstance(thread, dict)
    assert thread["id"].startswith("thr_")
    assert "ok" not in thread

    thread_id = thread["id"]
    listed = await client.get("/v1/threads")
    assert listed.status_code == 200
    threads = listed.json()
    assert isinstance(threads, list)
    assert any(t["id"] == thread_id for t in threads)

    detail = await client.get(f"/v1/threads/{thread_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["thread"]["id"] == thread_id
    assert isinstance(payload["items"], list)

    renamed = await client.patch(
        f"/v1/threads/{thread_id}",
        json={"title": "Contract test thread"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Contract test thread"

    archived = await client.delete(f"/v1/threads/{thread_id}")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True


@pytest.mark.asyncio
async def test_threads_summary(client: AsyncClient) -> None:
    await client.post("/v1/threads", json={})
    r = await client.get("/v1/threads/summary")
    assert r.status_code == 200
    summary = r.json()
    assert summary["total"] >= 1
    assert "active" in summary
