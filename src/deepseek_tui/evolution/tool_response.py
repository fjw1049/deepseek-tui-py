"""Structured tool responses for evolution main-agent tools."""

from __future__ import annotations

from typing import Any

from deepseek_tui.evolution.audit.store import LedgerRecord
from deepseek_tui.evolution.curated.store import CuratedMemoryStore, Target
from deepseek_tui.evolution.protocols import ApplyResult, ExperienceMutation


def build_evolution_tool_response(
    *,
    record: LedgerRecord,
    decision: str,
    apply_result: ApplyResult | None = None,
    mutation: ExperienceMutation | None = None,
    store: object | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """JSON payload returned to the model from memory_curate / skill_manage."""
    status = record.status
    ok = error is None and status not in ("denied", "failed", "rejected")
    payload: dict[str, Any] = {
        "ok": ok,
        "decision": decision,
        "status": status,
        "record_id": record.id,
        "kind": record.kind,
    }
    if error:
        payload["error"] = error
        return payload
    if apply_result is not None:
        if apply_result.message:
            payload["message"] = apply_result.message
        if apply_result.path:
            payload["path"] = apply_result.path
        if apply_result.details:
            payload.update(apply_result.details)
    if mutation is not None and isinstance(store, CuratedMemoryStore):
        target_raw = mutation.payload.get("target")
        if target_raw in ("memory", "user"):
            target: Target = target_raw  # type: ignore[assignment]
            payload["current_entries"] = store.live_entries(target)
            payload["usage"] = store.usage(target)
    return payload


def decision_from_record_status(status: str) -> str:
    if status == "proposed":
        return "propose"
    if status in ("denied", "rejected"):
        return "deny"
    if status == "applied":
        return "auto"
    if status == "pending_apply":
        return "auto"
    if status == "failed":
        return "deny"
    return "propose"
