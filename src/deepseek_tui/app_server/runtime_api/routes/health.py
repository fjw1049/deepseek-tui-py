"""GET /health and /healthz — connection probes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "deepseek-runtime-api", "mode": "local"}


@router.get("/healthz")
async def healthz_alias() -> dict[str, str]:
    return {"status": "ok", "service": "deepseek-runtime-api", "mode": "local"}
