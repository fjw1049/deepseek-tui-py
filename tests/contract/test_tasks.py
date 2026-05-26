"""GET/POST /v1/tasks — durable background task queue."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.app_server.runtime import AppRuntime
from deepseek_tui.app_server.server import build_fastapi_app
from deepseek_tui.config.models import Config, FeatureConfig


@pytest.mark.asyncio
async def test_list_tasks_unconfigured_returns_503(client: AsyncClient) -> None:
    r = await client.get("/v1/tasks")
    assert r.status_code == 503, r.text
    body = r.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert detail.get("error") == "runtime_error"
    else:
        assert body.get("error") == "runtime_error"


@pytest.fixture
async def tasks_client(runtime_data_dir) -> AsyncIterator[AsyncClient]:
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=True,
            subagents=False,
            automations=False,
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
async def test_list_tasks_empty_when_enabled(tasks_client: AsyncClient) -> None:
    r = await tasks_client.get("/v1/tasks")
    assert r.status_code == 200, r.text
    assert r.json() == []
