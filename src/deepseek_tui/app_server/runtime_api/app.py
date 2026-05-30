"""Build FastAPI app fragment for Workbench runtime API."""

from __future__ import annotations

from typing import Any

from deepseek_tui.app_server.runtime_api.approval_bridge import ApprovalBridge
from deepseek_tui.app_server.runtime_api.elevation_bridge import ElevationBridge
from deepseek_tui.app_server.runtime_api.auth import RuntimeAuthMiddleware
from deepseek_tui.app_server.runtime_api.routes import build_runtime_api_router


def attach_runtime_api(
    app: Any,
    *,
    auth_token: str | None = None,
    cors_origins: list[str] | None = None,
) -> tuple[ApprovalBridge, ElevationBridge]:
    """Mount parity routes and auth middleware on an existing FastAPI app.

    This is the single construction path used by ``server.build_fastapi_app``
    (production) and by contract tests. Tests must drive the runtime through
    this same call so middleware / state wiring stays in lockstep with prod.
    """
    bridge = ApprovalBridge()
    elevation = ElevationBridge()
    app.state.approval_bridge = bridge
    app.state.elevation_bridge = elevation
    app.state.runtime_auth_token = auth_token

    @app.get("/")
    async def runtime_api_root() -> dict[str, str]:
        return {
            "service": "deepseek-runtime-api",
            "hint": (
                "HTTP API only — open DeepSeek Workbench (Electron), "
                "not this URL in a browser."
            ),
            "health": "/health",
            "threads": "/v1/threads",
        }

    app.include_router(build_runtime_api_router())
    app.add_middleware(RuntimeAuthMiddleware, auth_token=auth_token)
    if cors_origins:
        attach_cors(app, cors_origins)
    return bridge, elevation


def attach_cors(app: Any, origins: list[str]) -> None:
    from starlette.middleware.cors import CORSMiddleware

    # Bearer tokens travel in the Authorization header, not cookies, so
    # ``allow_credentials`` stays False. Combining credentials=True with a
    # user-configurable origin list would widen the cross-site attack surface
    # for no benefit on a localhost-only runtime.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
