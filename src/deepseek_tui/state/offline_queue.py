from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.state.database import Database


@dataclass(slots=True)
class OfflineQueueRecord:
    id: int | None
    created_at: str
    payload_json: str
    status: str = "pending"
    attempt_count: int = 0


class OfflineQueueStore:
    def __init__(self, database: Database):
        self.database = database

    async def enqueue(self, record: OfflineQueueRecord) -> int:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            INSERT INTO offline_queue (created_at, payload_json, status, attempt_count)
            VALUES (?, ?, ?, ?)
            """,
            (record.created_at, record.payload_json, record.status, record.attempt_count),
        )
        await connection.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("offline queue insert did not return a row id")
        return int(row_id)

    async def list_pending(self) -> list[OfflineQueueRecord]:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, created_at, payload_json, status, attempt_count
            FROM offline_queue
            WHERE status = 'pending'
            ORDER BY id ASC
            """
        )
        rows = await cursor.fetchall()
        return [OfflineQueueRecord(**dict(row)) for row in rows]

    async def mark_done(self, item_id: int) -> None:
        connection = await self.database.connect()
        await connection.execute(
            "UPDATE offline_queue SET status = 'done' WHERE id = ?",
            (item_id,),
        )
        await connection.commit()
