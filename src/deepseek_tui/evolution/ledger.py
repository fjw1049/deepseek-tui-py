"""Experience ledger — policy, audit, apply."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

import aiosqlite

from deepseek_tui.evolution.audit.store import EvolutionAuditStore, LedgerRecord
from deepseek_tui.evolution.events import (
    EvolutionAppliedEvent,
    EvolutionRejectedEvent,
    EvolutionSuggestedEvent,
)
from deepseek_tui.evolution.policy import DefaultEvolutionPolicy
from deepseek_tui.evolution.protocols import ApplyResult, EvolutionBackend, ExperienceMutation
from deepseek_tui.evolution.sinks.trajectory import TrajectorySink
from deepseek_tui.post_turn.evidence import TurnEvidence

logger = logging.getLogger(__name__)

EmitFn = Callable[[object], Awaitable[None]]


class ExperienceLedger:
    def __init__(
        self,
        *,
        policy: DefaultEvolutionPolicy,
        audit: EvolutionAuditStore,
        backends: list[EvolutionBackend],
        emit: EmitFn | None = None,
        on_applied: Callable[[ExperienceMutation, ApplyResult], None] | None = None,
        trajectory: TrajectorySink | None = None,
    ) -> None:
        self._policy = policy
        self._audit = audit
        self._backends = backends
        self._emit = emit
        self._on_applied = on_applied
        self._trajectory = trajectory

    @property
    def audit(self) -> EvolutionAuditStore:
        return self._audit

    async def list_pending(
        self, *, thread_id: str | None = None, limit: int = 50
    ) -> list[LedgerRecord]:
        return await self._audit.list_pending(thread_id=thread_id, limit=limit)

    async def submit(
        self,
        mutation: ExperienceMutation,
        *,
        source: Literal["main_tool", "review", "flush"],
        evidence: TurnEvidence,
    ) -> LedgerRecord:
        decision = self._policy.decide(mutation, source=source)
        record = await self._audit.insert_proposed(mutation, evidence, source, decision)
        self._observe_trajectory(
            "submit",
            record=record,
            source=source,
            evidence=evidence,
            mutation=mutation,
            decision=decision,
        )

        if decision == "deny":
            await self._maybe_emit(
                EvolutionRejectedEvent(record_id=record.id, reason="policy deny")
            )
            return await self._fresh_record(record.id)

        if decision == "propose":
            summary = mutation.kind.replace("_", " ")
            await self._maybe_emit(
                EvolutionSuggestedEvent(
                    record_id=record.id,
                    kind=mutation.kind,
                    summary=summary,
                    asset_path=mutation.target_path,
                )
            )
            return await self._fresh_record(record.id)

        backend = self._backend_for(mutation)
        if backend is None:
            await self._audit.mark_failed(record.id, "no backend for mutation")
            return await self._fresh_record(record.id)
        result = await backend.apply(mutation)
        if result.success:
            await self._audit.mark_applied(record.id, result)
            await self._maybe_emit(
                EvolutionAppliedEvent(
                    record_id=record.id,
                    summary=result.message or mutation.kind,
                )
            )
            if self._on_applied:
                self._on_applied(mutation, result)
        else:
            await self._audit.mark_failed(record.id, result.message)
        return await self._fresh_record(record.id)

    async def _fresh_record(self, record_id: str) -> LedgerRecord:
        fresh = await self._audit.get(record_id)
        if fresh is None:
            raise RuntimeError(f"evolution record missing after submit: {record_id}")
        return fresh

    async def approve(self, record_id: str) -> LedgerRecord | None:
        record = await self._audit.get(record_id)
        if record is None or record.status != "proposed":
            return record
        mutation = await self._load_mutation(record_id)
        if mutation is None:
            await self._audit.mark_failed(record_id, "missing mutation payload")
            return await self._audit.get(record_id)
        backend = self._backend_for(mutation)
        if backend is None:
            await self._audit.mark_failed(record_id, "no backend")
            return await self._audit.get(record_id)
        result = await backend.apply(mutation)
        if result.success:
            await self._audit.mark_applied(record_id, result)
            await self._maybe_emit(
                EvolutionAppliedEvent(record_id=record_id, summary=result.message)
            )
            if self._on_applied:
                self._on_applied(mutation, result)
            final = await self._audit.get(record_id)
            if final is not None:
                self._observe_trajectory("approve", record=final, mutation=mutation)
        else:
            await self._audit.mark_failed(record_id, result.message)
        return await self._audit.get(record_id)

    async def reject(self, record_id: str, *, reason: str = "user rejected") -> LedgerRecord | None:
        async with aiosqlite.connect(self._audit._path) as conn:  # noqa: SLF001
            await conn.execute(
                "UPDATE evolution_events SET status = ?, reason = ? WHERE id = ?",
                ("rejected", reason, record_id),
            )
            await conn.commit()
        await self._maybe_emit(EvolutionRejectedEvent(record_id=record_id, reason=reason))
        record = await self._audit.get(record_id)
        if record is not None:
            self._observe_trajectory("reject", record=record, reason=reason)
        return record

    def _observe_trajectory(
        self,
        event: str,
        *,
        record: LedgerRecord,
        source: str | None = None,
        evidence: TurnEvidence | None = None,
        mutation: ExperienceMutation | None = None,
        decision: str | None = None,
        reason: str | None = None,
    ) -> None:
        if self._trajectory is None:
            return
        payload: dict[str, object] = {"status": record.status}
        if decision:
            payload["decision"] = decision
        if reason:
            payload["reason"] = reason
        if mutation is not None:
            payload["mutation_kind"] = mutation.kind
        self._trajectory.observe(
            event=event,
            record_id=record.id,
            kind=record.kind,
            source=source or record.source,
            thread_id=evidence.thread_id if evidence else record.thread_id,
            workspace=evidence.workspace if evidence else record.workspace,
            payload=payload,
        )

    def _backend_for(self, mutation: ExperienceMutation) -> EvolutionBackend | None:
        prefix = "memory_curate" if mutation.kind.startswith("memory_curate") else "skill_"
        target_name = "curated_memory" if prefix == "memory_curate" else "procedural_skill"
        for backend in self._backends:
            if backend.name == target_name:
                return backend
        return None

    async def _load_mutation(self, record_id: str) -> ExperienceMutation | None:
        async with aiosqlite.connect(self._audit._path) as conn:  # noqa: SLF001
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT kind, asset_path, diff_json, reason FROM evolution_events WHERE id = ?",
                (record_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        try:
            diff = json.loads(row["diff_json"] or "{}")
        except json.JSONDecodeError:
            diff = {}
        payload = diff.get("payload") if isinstance(diff.get("payload"), dict) else {}
        return ExperienceMutation(
            kind=str(row["kind"]),  # type: ignore[arg-type]
            payload=payload,
            target_path=row["asset_path"],
            reason=str(row["reason"] or ""),
            diff_before=diff.get("diff_before"),
            diff_after=diff.get("diff_after"),
        )

    async def _maybe_emit(self, event: object) -> None:
        if self._emit is None:
            return
        try:
            await self._emit(event)
        except Exception:
            logger.exception("evolution event emit failed")
