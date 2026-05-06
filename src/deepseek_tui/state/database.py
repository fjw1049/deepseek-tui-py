from __future__ import annotations

from pathlib import Path

import aiosqlite

from deepseek_tui.state.schema import SCHEMA_STATEMENTS


class Database:
    def __init__(self, path: Path):
        self.path = path.expanduser()
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = await aiosqlite.connect(self.path)
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    async def initialize(self) -> None:
        connection = await self.connect()
        for statement in SCHEMA_STATEMENTS:
            await connection.execute(statement)
        await connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
