from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.state.database import Database


@dataclass(slots=True)
class CheckpointRecord:
    id: int | None
    session_id: str
    created_at: str
    summary: str
    payload_json: str


class CheckpointsStore:
    def __init__(self, database: Database):
        self.database = database

    async def create(self, record: CheckpointRecord) -> int:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            INSERT INTO checkpoints (session_id, created_at, summary, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                record.session_id,
                record.created_at,
                record.summary,
                record.payload_json,
            ),
        )
        await connection.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("checkpoint insert did not return a row id")
        return int(row_id)

    async def get_latest_for_session(self, session_id: str) -> CheckpointRecord | None:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, session_id, created_at, summary, payload_json
            FROM checkpoints
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return CheckpointRecord(**dict(row))

    async def list_for_session(self, session_id: str) -> list[CheckpointRecord]:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, session_id, created_at, summary, payload_json
            FROM checkpoints
            WHERE session_id = ?
            ORDER BY id DESC
            """,
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [CheckpointRecord(**dict(row)) for row in rows]
