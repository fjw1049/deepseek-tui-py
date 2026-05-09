from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from deepseek_tui.state.database import Database


@dataclass(slots=True)
class ThreadRecord:
    """Simplified thread record for the legacy ThreadsStore interface.

    For full Rust-parity ThreadMetadata (19 fields), use
    ``state.session_manager.ThreadMetadata`` and ``SessionManager``.
    """

    id: str
    preview: str
    model_provider: str
    cwd: str
    status: str
    created_at: int
    updated_at: int
    archived: bool = False
    cli_version: str = ""
    source: str = "unknown"


class ThreadsStore:
    """Legacy thread store — thin wrapper for quick CRUD.

    For production multi-session lifecycle, prefer ``SessionManager``.
    """

    def __init__(self, database: Database):
        self.database = database

    async def upsert(self, record: ThreadRecord) -> None:
        connection = await self.database.connect()
        await connection.execute(
            """
            INSERT INTO threads (
                id, preview, model_provider, cwd, status, created_at, updated_at,
                archived, cli_version, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                preview = excluded.preview,
                model_provider = excluded.model_provider,
                cwd = excluded.cwd,
                status = excluded.status,
                updated_at = excluded.updated_at,
                archived = excluded.archived,
                cli_version = excluded.cli_version,
                source = excluded.source
            """,
            (
                record.id,
                record.preview,
                record.model_provider,
                record.cwd,
                record.status,
                record.created_at,
                record.updated_at,
                int(record.archived),
                record.cli_version,
                record.source,
            ),
        )
        await connection.commit()

    async def get(self, thread_id: str) -> ThreadRecord | None:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, preview, model_provider, cwd, status, created_at, updated_at,
                   archived, cli_version, source
            FROM threads
            WHERE id = ?
            """,
            (thread_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        data = dict(row)
        data["archived"] = bool(data["archived"])
        return ThreadRecord(**data)

    async def list_recent(
        self,
        *,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[ThreadRecord]:
        connection = await self.database.connect()
        if include_archived:
            cursor = await connection.execute(
                """
                SELECT id, preview, model_provider, cwd, status, created_at, updated_at,
                       archived, cli_version, source
                FROM threads
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            cursor = await connection.execute(
                """
                SELECT id, preview, model_provider, cwd, status, created_at, updated_at,
                       archived, cli_version, source
                FROM threads
                WHERE archived = 0
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = await cursor.fetchall()
        records: list[ThreadRecord] = []
        for row in rows:
            data = dict(row)
            data["archived"] = bool(data["archived"])
            records.append(ThreadRecord(**data))
        return records

    async def archive(self, thread_id: str, archived: bool = True) -> None:
        connection = await self.database.connect()
        now = int(datetime.now(timezone.utc).timestamp())
        if archived:
            await connection.execute(
                "UPDATE threads SET archived = 1, archived_at = ? WHERE id = ?",
                (now, thread_id),
            )
        else:
            await connection.execute(
                "UPDATE threads SET archived = 0, archived_at = NULL WHERE id = ?",
                (thread_id,),
            )
        await connection.commit()

    async def delete(self, thread_id: str) -> None:
        connection = await self.database.connect()
        await connection.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        await connection.commit()
