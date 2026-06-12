from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.config.models import Config, FeatureConfig


@pytest.fixture
async def cors_client(runtime_data_dir) -> AsyncIterator[AsyncClient]:
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=False,
            subagents=False,
            automations=False,
        ),
    )
    runtime = AppRuntime(config=config, working_directory=runtime_data_dir)
    app = build_fastapi_app(
        runtime,
        http_mode=True,
        insecure_no_auth=True,
        cors_origins=["http://localhost:5173"],
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_cors_allows_configured_origin(cors_client: AsyncClient) -> None:
    r = await cors_client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


@pytest.mark.asyncio
async def test_cors_preflight_v1_threads(cors_client: AsyncClient) -> None:
    r = await cors_client.options(
        "/v1/threads",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "POST" in (r.headers.get("access-control-allow-methods") or "")


@pytest.mark.asyncio
async def test_cors_does_not_allow_credentials(cors_client: AsyncClient) -> None:
    """Bearer tokens travel in Authorization headers, not cookies — combining
    user-configurable origins with allow_credentials=True would widen the
    cross-site attack surface for no benefit on a localhost runtime."""
    r = await cors_client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )
    # Starlette only sets the header when credentials=True, so its absence is
    # the contract.
    assert r.headers.get("access-control-allow-credentials") is None
