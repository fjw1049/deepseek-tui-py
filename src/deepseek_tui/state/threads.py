from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.state.database import Database


@dataclass(slots=True)
class ThreadRecord:
    id: str
    preview: str
    model: str
    workspace: str
    mode: str
    status: str
    created_at: str
    updated_at: str
    archived: bool = False
    system_prompt: str | None = None


class ThreadsStore:
    def __init__(self, database: Database):
        self.database = database

    async def upsert(self, record: ThreadRecord) -> None:
        connection = await self.database.connect()
        await connection.execute(
            """
            INSERT INTO threads (
                id, preview, model, workspace, mode, status, created_at, updated_at,
                archived, system_prompt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                preview = excluded.preview,
                model = excluded.model,
                workspace = excluded.workspace,
                mode = excluded.mode,
                status = excluded.status,
                updated_at = excluded.updated_at,
                archived = excluded.archived,
                system_prompt = excluded.system_prompt
            """,
            (
                record.id,
                record.preview,
                record.model,
                record.workspace,
                record.mode,
                record.status,
                record.created_at,
                record.updated_at,
                int(record.archived),
                record.system_prompt,
            ),
        )
        await connection.commit()

    async def get(self, thread_id: str) -> ThreadRecord | None:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, preview, model, workspace, mode, status, created_at, updated_at,
                   archived, system_prompt
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
                SELECT id, preview, model, workspace, mode, status, created_at, updated_at,
                       archived, system_prompt
                FROM threads
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            cursor = await connection.execute(
                """
                SELECT id, preview, model, workspace, mode, status, created_at, updated_at,
                       archived, system_prompt
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
        await connection.execute(
            "UPDATE threads SET archived = ? WHERE id = ?",
            (int(archived), thread_id),
        )
        await connection.commit()

    async def delete(self, thread_id: str) -> None:
        connection = await self.database.connect()
        await connection.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        await connection.commit()
