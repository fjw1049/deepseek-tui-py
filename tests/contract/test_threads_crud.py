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


def test_aggregate_thread_usage_bucket_sums_turns() -> None:
    from datetime import datetime, timezone

    from deepseek_tui.server.threads import (
        RuntimeTurnStatus,
        TurnRecord,
        aggregate_thread_usage_bucket,
        thread_usage_response,
    )

    now = datetime.now(timezone.utc)
    turns = [
        TurnRecord(
            id="turn_a",
            thread_id="thr_test",
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="a",
            created_at=now,
            usage={
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
                "cache_hit_tokens": 800,
                "cache_miss_tokens": 200,
                "cost_usd": 0.01,
                "cost_cny": 0.07,
                "turns": 1,
            },
        ),
        TurnRecord(
            id="turn_b",
            thread_id="thr_test",
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="b",
            created_at=now,
            usage={
                "input_tokens": 500,
                "output_tokens": 100,
                "total_tokens": 600,
                "cache_hit_tokens": 400,
                "cache_miss_tokens": 100,
                "cost_usd": 0.005,
                "cost_cny": 0.035,
                "turns": 1,
            },
        ),
    ]
    bucket = aggregate_thread_usage_bucket("thr_test", turns)
    assert bucket["input_tokens"] == 1500
    assert bucket["output_tokens"] == 300
    assert bucket["cached_tokens"] == 1200
    assert bucket["cache_miss_tokens"] == 300
    assert bucket["cache_hit_rate"] == pytest.approx(0.8)
    assert bucket["turns"] == 2
    response = thread_usage_response("thr_test", turns)
    assert response["group_by"] == "thread"
    assert len(response["buckets"]) == 1
    assert response["buckets"][0]["thread_id"] == "thr_test"


def test_aggregate_thread_usage_bucket_includes_live_usage() -> None:
    from deepseek_tui.server.threads import aggregate_thread_usage_bucket

    bucket = aggregate_thread_usage_bucket(
        "thr_live",
        [],
        live_usage={
            "input_tokens": 1200,
            "output_tokens": 300,
            "total_tokens": 1500,
            "cache_hit_tokens": 900,
            "cache_miss_tokens": 100,
            "cost_usd": 0.02,
            "turns": 3,
        },
    )
    assert bucket["input_tokens"] == 1200
    assert bucket["output_tokens"] == 300
    assert bucket["turns"] == 3
    assert bucket["cache_hit_rate"] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_thread_usage_endpoint(client: AsyncClient) -> None:
    create = await client.post("/v1/threads", json={"model": "deepseek-chat"})
    assert create.status_code == 201
    thread_id = create.json()["id"]

    empty = await client.get(
        f"/v1/usage?group_by=thread&thread_id={thread_id}",
    )
    assert empty.status_code == 200
    payload = empty.json()
    assert payload["group_by"] == "thread"
    assert payload["buckets"] == []

    missing = await client.get("/v1/usage?group_by=thread&thread_id=thr_missing")
    assert missing.status_code == 404

    bad_group = await client.get(
        f"/v1/usage?group_by=day&thread_id={thread_id}",
    )
    assert bad_group.status_code == 400
