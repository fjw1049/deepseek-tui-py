"""POST /v1/elevations/{id} — resolve a pending sandbox elevation (L3)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import body, elevation_bridge

router = APIRouter(prefix="/v1")


class DecideElevationBody(BaseModel):
    decision: str


@router.get("/elevations/pending")
async def list_pending_elevations(request: Request) -> list[dict[str, object]]:
    bridge = elevation_bridge(request)
    thread_id = request.query_params.get("thread_id")
    return bridge.list_pending(thread_id=thread_id or None)


@router.post("/elevations/{elevation_id}")
async def decide_elevation(request: Request, elevation_id: str) -> dict[str, object]:
    bridge = elevation_bridge(request)
    payload = DecideElevationBody.model_validate(await body(request))
    decision = payload.decision.strip().lower()
    if decision not in {"allow", "deny", "approve", "reject", "elevate"}:
        raise api_error(400, "decision must be allow or deny", error="invalid_decision")
    approved = decision in {"allow", "approve", "elevate"}
    if not bridge.resolve(elevation_id, approved):
        raise api_error(
            404,
            f"elevation not pending: {elevation_id}",
            error="elevation_not_found",
        )
    return {
        "ok": True,
        "elevation_id": elevation_id,
        "decision": "allow" if approved else "deny",
    }
