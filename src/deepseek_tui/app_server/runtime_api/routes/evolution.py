"""Evolution ledger approval routes for Workbench."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import body, manager

router = APIRouter(prefix="/v1")


class RejectEvolutionBody(BaseModel):
    reason: str = "user rejected"


def _record_to_dict(record: object) -> dict[str, object]:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    return {"repr": repr(record)}


async def _ledger_for_thread(request: Request, thread_id: str):
    mgr = manager(request)
    try:
        thread = await mgr.get_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    async with mgr._active_lock:
        state = mgr._active.get(thread_id)
    if state is None:
        await mgr._ensure_engine_loaded(thread)
        async with mgr._active_lock:
            state = mgr._active.get(thread_id)
    if state is None:
        raise api_error(503, "thread engine not loaded", error="engine_not_loaded")
    pipeline = getattr(state.engine, "_evolution_pipeline", None)
    if pipeline is None:
        raise api_error(503, "evolution not enabled", error="evolution_disabled")
    return pipeline.ledger


@router.get("/evolution/pending")
async def list_pending_evolution(
    request: Request,
) -> list[dict[str, object]]:
    thread_id = request.query_params.get("thread_id")
    mgr = manager(request)
    if thread_id:
        ledger = await _ledger_for_thread(request, thread_id)
        records = await ledger.list_pending(thread_id=thread_id)
    else:
        from deepseek_tui.evolution.audit.store import EvolutionAuditStore

        audit = EvolutionAuditStore(mgr.config.resolved_database_path())
        records = await audit.list_pending()
    return [_record_to_dict(r) for r in records]


@router.post("/evolution/{record_id}/approve")
async def approve_evolution(
    request: Request, record_id: str
) -> dict[str, object]:
    thread_id = request.query_params.get("thread_id")
    if not thread_id:
        raise api_error(400, "thread_id query param required", error="missing_thread_id")
    ledger = await _ledger_for_thread(request, thread_id)
    record = await ledger.approve(record_id)
    if record is None:
        raise api_error(404, f"evolution record not found: {record_id}", error="not_found")
    return {"ok": True, "record": _record_to_dict(record)}


@router.post("/evolution/{record_id}/reject")
async def reject_evolution(
    request: Request, record_id: str
) -> dict[str, object]:
    thread_id = request.query_params.get("thread_id")
    if not thread_id:
        raise api_error(400, "thread_id query param required", error="missing_thread_id")
    payload = RejectEvolutionBody.model_validate(await body(request))
    ledger = await _ledger_for_thread(request, thread_id)
    record = await ledger.reject(record_id, reason=payload.reason.strip() or "user rejected")
    if record is None:
        raise api_error(404, f"evolution record not found: {record_id}", error="not_found")
    return {"ok": True, "record": _record_to_dict(record)}
