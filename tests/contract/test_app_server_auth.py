"""Legacy app-server mode (``http_mode=False``) enforces the same bearer auth.

Historically only the Workbench runtime API (``--http``) attached
``RuntimeAuthMiddleware``; the default ``deepseek serve`` transport exposed
``POST /tool`` & co. to any local (or, with ``--host 0.0.0.0``, remote)
process. Both modes now resolve the same default-deny guard.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.config.models import Config, FeatureConfig


def _legacy_app(runtime_data_dir: object, **kwargs: object) -> object:
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=False,
            subagents=False,
            automations=False,
        ),
    )
    runtime = AppRuntime(config=config, working_directory=runtime_data_dir)  # type: ignore[arg-type]
    return build_fastapi_app(runtime, http_mode=False, **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_legacy_mode_requires_token(runtime_data_dir: object) -> None:
    app = _legacy_app(runtime_data_dir, auth_token="legacy-token")
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied_v1 = await client.get("/v1/jobs")
        assert denied_v1.status_code == 401

        denied_root = await client.get("/jobs")
        assert denied_root.status_code == 401

        allowed = await client.get(
            "/v1/jobs",
            headers={"Authorization": "Bearer legacy-token"},
        )
        assert allowed.status_code == 200

        # Health checks stay unauthenticated, matching http mode.
        health = await client.get("/healthz")
        assert health.status_code == 200


@pytest.mark.asyncio
async def test_legacy_mode_insecure_allows(runtime_data_dir: object) -> None:
    app = _legacy_app(runtime_data_dir, insecure_no_auth=True)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.get("/v1/jobs")
        assert allowed.status_code == 200
