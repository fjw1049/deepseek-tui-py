"""SQLite audit store for evolution events."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from deepseek_tui.evolution.protocols import ApplyResult, ExperienceMutation
from deepseek_tui.post_turn.evidence import TurnEvidence


@dataclass(frozen=True)
class LedgerRecord:
    id: str
    thread_id: str
    workspace: str
    kind: str
    status: str
    asset_path: str | None
    reason: str
    source: str
    source_turn_id: str
    created_at: float


class EvolutionAuditStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path.expanduser()

    async def initialize(self) -> None:
        from deepseek_tui.state.database import Database

        db = Database(self._path)
        await db.initialize()

    async def insert_proposed(
        self,
        mutation: ExperienceMutation,
        evidence: TurnEvidence,
        source: str,
        decision: str,
    ) -> LedgerRecord:
        record_id = uuid.uuid4().hex
        status = {
            "auto": "pending_apply",
            "propose": "proposed",
            "deny": "denied",
        }.get(decision, "proposed")
        created_at = time.time()
        diff_json = json.dumps(
            {
                "payload": mutation.payload,
                "diff_before": mutation.diff_before,
                "diff_after": mutation.diff_after,
            },
            ensure_ascii=False,
        )
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute(
                """
                INSERT INTO evolution_events (
                    id, thread_id, workspace, kind, status, asset_path,
                    diff_json, reason, source, source_turn_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    evidence.thread_id,
                    evidence.workspace,
                    mutation.kind,
                    status,
                    mutation.target_path,
                    diff_json,
                    mutation.reason,
                    source,
                    evidence.turn_id,
                    created_at,
                ),
            )
            await conn.commit()
        return LedgerRecord(
            id=record_id,
            thread_id=evidence.thread_id,
            workspace=evidence.workspace,
            kind=mutation.kind,
            status=status,
            asset_path=mutation.target_path,
            reason=mutation.reason,
            source=source,
            source_turn_id=evidence.turn_id,
            created_at=created_at,
        )

    async def mark_applied(self, record_id: str, result: ApplyResult) -> None:
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute(
                """
                UPDATE evolution_events
                SET status = ?, asset_path = COALESCE(?, asset_path), reason = ?
                WHERE id = ?
                """,
                ("applied", result.path, result.message, record_id),
            )
            await conn.commit()

    async def mark_failed(self, record_id: str, message: str) -> None:
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute(
                "UPDATE evolution_events SET status = ?, reason = ? WHERE id = ?",
                ("failed", message, record_id),
            )
            await conn.commit()

    async def get(self, record_id: str) -> LedgerRecord | None:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT * FROM evolution_events WHERE id = ?", (record_id,)
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    async def list_pending(
        self, *, thread_id: str | None = None, limit: int = 50
    ) -> list[LedgerRecord]:
        async with aiosqlite.connect(self._path) as conn:
            conn.row_factory = aiosqlite.Row
            if thread_id:
                cur = await conn.execute(
                    """
                    SELECT * FROM evolution_events
                    WHERE status = 'proposed' AND thread_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (thread_id, limit),
                )
            else:
                cur = await conn.execute(
                    """
                    SELECT * FROM evolution_events
                    WHERE status = 'proposed'
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                )
            rows = await cur.fetchall()
        return [_row_to_record(row) for row in rows]


def _row_to_record(row: aiosqlite.Row) -> LedgerRecord:
    return LedgerRecord(
        id=str(row["id"]),
        thread_id=str(row["thread_id"]),
        workspace=str(row["workspace"]),
        kind=str(row["kind"]),
        status=str(row["status"]),
        asset_path=row["asset_path"],
        reason=str(row["reason"] or ""),
        source=str(row["source"]),
        source_turn_id=str(row["source_turn_id"] or ""),
        created_at=float(row["created_at"]),
    )
