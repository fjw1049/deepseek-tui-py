from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from deepseek_tui.tools.registry import ToolContext


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

    # Archive flows through PATCH; DELETE is intentionally not exposed because
    # GUI v1 never deletes threads — see WORKBENCH_HANDOVER §10.
    archived = await client.patch(
        f"/v1/threads/{thread_id}",
        json={"archived": True},
    )
    assert archived.status_code == 200
    assert archived.json()["archived"] is True

    bad_json = await client.post(
        "/v1/threads",
        content="{not json",
        headers={"content-type": "application/json"},
    )
    assert bad_json.status_code == 400
    assert bad_json.json()["detail"]["error"] == "invalid_json"


@pytest.mark.asyncio
async def test_create_thread_persists_trust_mode(client: AsyncClient) -> None:
    r = await client.post("/v1/threads", json={"trust_mode": True, "auto_approve": False})
    assert r.status_code == 201
    body = r.json()
    assert body["trust_mode"] is True
    assert body["auto_approve"] is False


@pytest.mark.asyncio
async def test_thread_active_endpoint(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={"model": "deepseek-chat"})
    assert create.status_code == 201
    thread_id = create.json()["id"]

    active = await client.get(f"/v1/threads/{thread_id}/active")
    assert active.status_code == 200
    assert active.json() == {"active": False}


@pytest.mark.asyncio
async def test_thread_warmup_endpoint_loads_engine(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        wd = kwargs.get("working_directory", Path("."))
        ctx = ToolContext(working_directory=Path(wd))  # type: ignore[arg-type]
        return SimpleNamespace(tool_context=ctx, run=AsyncMock())

    monkeypatch.setattr("deepseek_tui.engine.orchestrator.Engine.create", fake_create)

    create = await client.post("/v1/threads", json={"model": "deepseek-chat"})
    assert create.status_code == 201
    thread_id = create.json()["id"]

    first = await client.post(f"/v1/threads/{thread_id}/warmup")
    assert first.status_code == 200
    assert first.json()["status"] == "ready"
    assert first.json()["thread_id"] == thread_id

    second = await client.post(f"/v1/threads/{thread_id}/warmup")
    assert second.status_code == 200
    assert calls == 1


@pytest.mark.asyncio
async def test_threads_summary(client: AsyncClient) -> None:
    await client.post("/v1/threads", json={})
    r = await client.get("/v1/threads/summary")
    assert r.status_code == 200
    summary = r.json()
    assert summary["total"] >= 1
    assert "active" in summary
