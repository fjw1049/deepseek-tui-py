"""GET /health and /healthz — connection probes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "deepseek-runtime-api", "mode": "local"}


@router.get("/healthz")
async def healthz_alias() -> dict[str, str]:
    return {"status": "ok", "service": "deepseek-runtime-api", "mode": "local"}


@router.get("/health/ready")
async def health_ready(request: Request) -> dict[str, object]:
    """Readiness probe — HTTP is up; MCP may still be warming in background."""
    from deepseek_tui.app_server.runtime_api.runtime_delegate import runtime_from_request

    runtime = runtime_from_request(request)
    mcp = runtime.mcp_preload_status()
    warming = bool(mcp.get("warming"))
    return {
        "status": "ok",
        "service": "deepseek-runtime-api",
        "ready": not warming,
        "mcp": mcp,
    }
