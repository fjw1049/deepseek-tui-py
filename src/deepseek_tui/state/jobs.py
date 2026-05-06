from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.state.database import Database


@dataclass(slots=True)
class JobRecord:
    id: str
    name: str
    status: str
    progress: int | None
    detail: str | None
    created_at: str
    updated_at: str


class JobsStore:
    def __init__(self, database: Database):
        self.database = database

    async def upsert(self, record: JobRecord) -> None:
        connection = await self.database.connect()
        await connection.execute(
            """
            INSERT INTO jobs (id, name, status, progress, detail, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                status = excluded.status,
                progress = excluded.progress,
                detail = excluded.detail,
                updated_at = excluded.updated_at
            """,
            (
                record.id,
                record.name,
                record.status,
                record.progress,
                record.detail,
                record.created_at,
                record.updated_at,
            ),
        )
        await connection.commit()

    async def get(self, job_id: str) -> JobRecord | None:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, name, status, progress, detail, created_at, updated_at
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return JobRecord(**dict(row))

    async def list_recent(self, limit: int = 50) -> list[JobRecord]:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, name, status, progress, detail, created_at, updated_at
            FROM jobs
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [JobRecord(**dict(row)) for row in rows]
