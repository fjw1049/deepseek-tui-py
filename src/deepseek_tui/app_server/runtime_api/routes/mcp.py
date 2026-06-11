"""POST /v1/mcp/startup — start enabled MCP servers (Workbench Settings reload).

The Workbench reloads MCP config from disk then asks the runtime to (re)connect
its enabled servers. The legacy router exposed this under ``/legacy/mcp/startup``
only; the GUI talks exclusively to ``/v1/*`` so the parity route lives here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from deepseek_tui.capabilities.mcp import (
    mcp_preload_status_response,
    mcp_startup_response,
)

router = APIRouter(prefix="/v1")


@router.post("/mcp/startup")
async def mcp_startup(request: Request) -> dict[str, Any]:
    return await mcp_startup_response(request)


@router.get("/mcp/preload-status")
async def mcp_preload_status(request: Request) -> dict[str, Any]:
    return mcp_preload_status_response(request)
