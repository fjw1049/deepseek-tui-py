from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from deepseek_tui.state.database import Database


@dataclass(slots=True)
class MessageRecord:
    id: int | None
    thread_id: str
    role: str
    content_json: str
    created_at: str

    @property
    def content(self) -> Any:
        return json.loads(self.content_json)


class MessagesStore:
    def __init__(self, database: Database):
        self.database = database

    async def append(self, record: MessageRecord) -> int:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            INSERT INTO messages (thread_id, role, content_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (record.thread_id, record.role, record.content_json, record.created_at),
        )
        await connection.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("message insert did not return a row id")
        return int(row_id)

    async def list_for_thread(self, thread_id: str) -> list[MessageRecord]:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, thread_id, role, content_json, created_at
            FROM messages
            WHERE thread_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (thread_id,),
        )
        rows = await cursor.fetchall()
        return [MessageRecord(**dict(row)) for row in rows]


def encode_content(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_content(raw: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads(raw))
