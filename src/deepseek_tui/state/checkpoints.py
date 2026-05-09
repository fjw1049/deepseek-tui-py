from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.state.database import Database


@dataclass(slots=True)
class CheckpointRecord:
    thread_id: str
    checkpoint_id: str
    state_json: str
    created_at: int


class CheckpointsStore:
    def __init__(self, database: Database):
        self.database = database

    async def save(self, record: CheckpointRecord) -> None:
        connection = await self.database.connect()
        await connection.execute(
            """
            INSERT INTO checkpoints (thread_id, checkpoint_id, state_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id, checkpoint_id) DO UPDATE SET
                state_json = excluded.state_json,
                created_at = excluded.created_at
            """,
            (
                record.thread_id,
                record.checkpoint_id,
                record.state_json,
                record.created_at,
            ),
        )
        await connection.commit()

    async def load(
        self, thread_id: str, checkpoint_id: str | None = None
    ) -> CheckpointRecord | None:
        connection = await self.database.connect()
        if checkpoint_id is not None:
            cursor = await connection.execute(
                """
                SELECT thread_id, checkpoint_id, state_json, created_at
                FROM checkpoints
                WHERE thread_id = ? AND checkpoint_id = ?
                """,
                (thread_id, checkpoint_id),
            )
        else:
            cursor = await connection.execute(
                """
                SELECT thread_id, checkpoint_id, state_json, created_at
                FROM checkpoints
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (thread_id,),
            )
        row = await cursor.fetchone()
        if row is None:
            return None
        return CheckpointRecord(**dict(row))

    async def list_for_thread(
        self, thread_id: str, limit: int = 100
    ) -> list[CheckpointRecord]:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT thread_id, checkpoint_id, state_json, created_at
            FROM checkpoints
            WHERE thread_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (thread_id, limit),
        )
        rows = await cursor.fetchall()
        return [CheckpointRecord(**dict(row)) for row in rows]

    async def delete(self, thread_id: str, checkpoint_id: str) -> None:
        connection = await self.database.connect()
        await connection.execute(
            "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id = ?",
            (thread_id, checkpoint_id),
        )
        await connection.commit()
