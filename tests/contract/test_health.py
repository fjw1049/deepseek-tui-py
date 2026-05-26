from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "deepseek-runtime-api"


@pytest.mark.asyncio
async def test_runtime_api_root(client: AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "deepseek-runtime-api"
    assert "hint" in body


@pytest.mark.asyncio
async def test_healthz_alias(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # /healthz must report the same service as /health so callers cannot
    # branch on which probe they happened to hit.
    assert body["service"] == "deepseek-runtime-api"
    assert body["mode"] == "local"
