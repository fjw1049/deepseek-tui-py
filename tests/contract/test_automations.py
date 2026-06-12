"""Contract tests for /v1/automations and /v1/triggers."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.config.models import Config, FeatureConfig


@pytest.mark.asyncio
async def test_list_automations_unconfigured_returns_503(client: AsyncClient) -> None:
    r = await client.get("/v1/automations")
    assert r.status_code == 503, r.text


@pytest.fixture
async def automations_client(
    runtime_data_dir, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    # Isolate from the developer's real ~/.deepseek automations store.
    monkeypatch.setenv(
        "DEEPSEEK_AUTOMATIONS_DIR", str(runtime_data_dir / "automations-home")
    )
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=True,
            subagents=False,
            automations=True,
        ),
    )
    runtime = await AppRuntime.create(config=config, working_directory=runtime_data_dir)
    app = build_fastapi_app(
        runtime,
        http_mode=True,
        insecure_no_auth=True,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_automations_crud_and_trigger(automations_client: AsyncClient) -> None:
    r = await automations_client.get("/v1/automations")
    assert r.status_code == 200
    assert r.json() == []

    body = {
        "name": "test-job",
        "prompt": "say hi",
        "rrule": "FREQ=HOURLY;INTERVAL=1",
        "delivery": {"mode": "silent"},
    }
    r = await automations_client.post("/v1/automations", json=body)
    assert r.status_code == 201, r.text
    created = r.json()
    automation_id = created["id"]
    assert created["name"] == "test-job"

    r = await automations_client.get(f"/v1/automations/{automation_id}")
    assert r.status_code == 200
    assert r.json()["id"] == automation_id

    r = await automations_client.post("/v1/triggers", json={"prompt": "ping"})
    assert r.status_code == 200, r.text
    trigger = r.json()
    assert trigger["status"] == "enqueued"
    assert trigger.get("task_id")

    r = await automations_client.delete(f"/v1/automations/{automation_id}")
    assert r.status_code == 200
