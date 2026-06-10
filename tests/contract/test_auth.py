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

        # Query-string tokens must NOT be honoured — they leak via proxy logs
        # and OS process listings. Only Authorization / x-deepseek-runtime-token
        # are accepted.
        query_only = await client.get(f"/v1/threads?token={token}")
        assert query_only.status_code == 401


@pytest.mark.asyncio
async def test_legacy_routes_require_token_when_configured(
    authed_runtime_app: tuple[object, str],
) -> None:
    """Auth is default-deny: /legacy/* must be guarded, not just /v1/*."""
    app, token = authed_runtime_app
    from httpx import ASGITransport

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied_get = await client.get("/legacy/jobs")
        assert denied_get.status_code == 401

        denied_post = await client.post("/legacy/prompt", json={"prompt": "hi"})
        assert denied_post.status_code == 401

        allowed = await client.get(
            "/legacy/jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert allowed.status_code == 200
