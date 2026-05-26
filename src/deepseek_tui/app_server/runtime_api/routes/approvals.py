"""POST /v1/approvals/{id} — resolve a pending tool approval."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import approval_bridge, body

router = APIRouter(prefix="/v1")


class DecideApprovalBody(BaseModel):
    decision: str
    remember: bool = False


@router.get("/approvals/pending")
async def list_pending_approvals(request: Request) -> list[dict[str, str]]:
    bridge = approval_bridge(request)
    thread_id = request.query_params.get("thread_id")
    return bridge.list_pending(thread_id=thread_id or None)


@router.post("/approvals/{approval_id}")
async def decide_approval(request: Request, approval_id: str) -> dict[str, object]:
    bridge = approval_bridge(request)
    payload = DecideApprovalBody.model_validate(await body(request))
    decision = payload.decision.strip().lower()
    if decision not in {"allow", "deny", "approve", "reject"}:
        raise api_error(400, "decision must be allow or deny", error="invalid_decision")
    approved = decision in {"allow", "approve"}
    if not bridge.resolve(approval_id, approved, remember=payload.remember):
        raise api_error(
            404, f"approval not pending: {approval_id}", error="approval_not_found"
        )
    return {
        "ok": True,
        "approval_id": approval_id,
        "decision": "allow" if approved else "deny",
    }
