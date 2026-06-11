"""Evolution ledger approval routes for Workbench."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import body, manager
from deepseek_tui.capabilities.evolution import (
    evolution_ledger_for_thread,
    evolution_record_to_dict,
)

router = APIRouter(prefix="/v1")


class RejectEvolutionBody(BaseModel):
    reason: str = "user rejected"


@router.get("/evolution/pending")
async def list_pending_evolution(
    request: Request,
) -> list[dict[str, object]]:
    thread_id = request.query_params.get("thread_id")
    mgr = manager(request)
    if thread_id:
        ledger = await evolution_ledger_for_thread(request, thread_id)
        records = await ledger.list_pending(thread_id=thread_id)
    else:
        from deepseek_tui.evolution.audit.store import EvolutionAuditStore

        audit = EvolutionAuditStore(mgr.config.resolved_database_path())
        records = await audit.list_pending()
    return [evolution_record_to_dict(r) for r in records]


@router.post("/evolution/{record_id}/approve")
async def approve_evolution(
    request: Request, record_id: str
) -> dict[str, object]:
    thread_id = request.query_params.get("thread_id")
    if not thread_id:
        raise api_error(400, "thread_id query param required", error="missing_thread_id")
    ledger = await evolution_ledger_for_thread(request, thread_id)
    record = await ledger.approve(record_id)
    if record is None:
        raise api_error(404, f"evolution record not found: {record_id}", error="not_found")
    return {"ok": True, "record": evolution_record_to_dict(record)}


@router.post("/evolution/{record_id}/reject")
async def reject_evolution(
    request: Request, record_id: str
) -> dict[str, object]:
    thread_id = request.query_params.get("thread_id")
    if not thread_id:
        raise api_error(400, "thread_id query param required", error="missing_thread_id")
    payload = RejectEvolutionBody.model_validate(await body(request))
    ledger = await evolution_ledger_for_thread(request, thread_id)
    record = await ledger.reject(record_id, reason=payload.reason.strip() or "user rejected")
    if record is None:
        raise api_error(404, f"evolution record not found: {record_id}", error="not_found")
    return {"ok": True, "record": evolution_record_to_dict(record)}
