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
    content: str
    item_json: str | None
    created_at: int

    @property
    def item(self) -> Any | None:
        if self.item_json is None:
            return None
        return json.loads(self.item_json)


class MessagesStore:
    def __init__(self, database: Database):
        self.database = database

    async def append(
        self,
        thread_id: str,
        role: str,
        content: str,
        item: Any | None = None,
        created_at: int | None = None,
    ) -> int:
        connection = await self.database.connect()
        item_json = json.dumps(item) if item is not None else None
        if created_at is None:
            from datetime import datetime, timezone

            created_at = int(datetime.now(timezone.utc).timestamp())
        cursor = await connection.execute(
            """
            INSERT INTO messages (thread_id, role, content, item_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (thread_id, role, content, item_json, created_at),
        )
        await connection.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("message insert did not return a row id")
        return int(row_id)

    async def list_for_thread(
        self, thread_id: str, limit: int = 500
    ) -> list[MessageRecord]:
        connection = await self.database.connect()
        cursor = await connection.execute(
            """
            SELECT id, thread_id, role, content, item_json, created_at
            FROM messages
            WHERE thread_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (thread_id, limit),
        )
        rows = await cursor.fetchall()
        return [MessageRecord(**dict(row)) for row in rows]

    async def clear_for_thread(self, thread_id: str) -> int:
        connection = await self.database.connect()
        cursor = await connection.execute(
            "DELETE FROM messages WHERE thread_id = ?", (thread_id,)
        )
        await connection.commit()
        return cursor.rowcount


def encode_content(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_content(raw: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads(raw))
