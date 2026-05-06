from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from deepseek_tui.state.database import Database


@dataclass(slots=True)
class SessionRecord:
    id: str
    title: str
    created_at: str
    updated_at: str
    transcript_json: str

    @property
    def transcript(self) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], json.loads(self.transcript_json))


class SessionsStore:
    def __init__(self, database: Database):
        self.database = database

    async def upsert(self, record: SessionRecord) -> None:
        connection = await self.database.connect()
        await connection.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at, transcript_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                updated_at = excluded.updated_at,
                transcript_json = excluded.transcript_json
            """,
            (
                record.id,
                record.title,
                record.created_at,
                record.updated_at,
                record.transcript_json,
            ),
        )
        await connection.commit()

    async def delete(self, session_id: str) -> None:
        connection = await self.database.connect()
        await connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await connection.commit()

    async def get(self, session_id: str) -> SessionRecord | None:
        connection = await self.database.connect()
        cursor = await connection.execute(
            "SELECT id, title, created_at, updated_at, transcript_json FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return SessionRecord(**dict(row))

    async def list_all(self) -> list[SessionRecord]:
        connection = await self.database.connect()
        cursor = await connection.execute(
            "SELECT id, title, created_at, updated_at, transcript_json "
            "FROM sessions ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [SessionRecord(**dict(row)) for row in rows]
