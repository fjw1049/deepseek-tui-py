"""GET /v1/workspace/status — diagnostic dialog."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from deepseek_tui.app_server.runtime_api.errors import api_error

router = APIRouter(prefix="/v1")


@router.get("/workspace/status")
async def workspace_status(request: Request) -> dict[str, Any]:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise api_error(503, "runtime not configured")
    return await runtime.workspace_status()
