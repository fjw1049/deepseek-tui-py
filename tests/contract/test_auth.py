from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_v1_requires_token_when_configured(
    authed_runtime_app: tuple[object, str],
) -> None:
    app, token = authed_runtime_app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/v1/threads")
        assert denied.status_code == 401

        allowed = await client.get(
            "/v1/threads",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert allowed.status_code == 200

        health = await client.get("/health")
        assert health.status_code == 200
