"""Tests for state persistence hardening.

- SQLite connections must enable WAL + busy_timeout (concurrent reader/writer
  safety, mirrors memory/native/store.py pragmas).
- The JSONL session index must survive a single corrupt line.
- unarchive() must restore the thread status that archive() overwrote.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.state.database import Database
from deepseek_tui.state.session_manager import (
    SessionIndex,
    SessionIndexEntry,
    SessionManager,
    ThreadStatus,
)


@pytest.mark.asyncio
async def test_database_enables_wal_and_busy_timeout(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.sqlite3")
    try:
        conn = await db.connect()
        cursor = await conn.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row[0].lower() == "wal"
        cursor = await conn.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
        assert row[0] == 5000
    finally:
        await db.close()


def test_session_index_skips_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "session_index.jsonl"
    index = SessionIndex(path)
    index.append(
        SessionIndexEntry(thread_id="a", thread_name="alpha", updated_at=1)
    )
    with path.open("a", encoding="utf-8") as f:
        f.write("{not valid json\n")
        f.write(json.dumps({"missing_thread_id": True}) + "\n")
    index.append(
        SessionIndexEntry(thread_id="b", thread_name="beta", updated_at=2)
    )

    entries = index.load_map()
    assert set(entries) == {"a", "b"}
    assert entries["a"].thread_name == "alpha"
    assert entries["b"].thread_name == "beta"


@pytest.mark.asyncio
async def test_unarchive_restores_idle_status(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.sqlite3")
    await db.initialize()
    try:
        mgr = SessionManager(db, index_path=tmp_path / "session_index.jsonl")
        _, meta = await mgr.create_session("deepseek-chat", tmp_path)

        await mgr.archive(meta.id)
        archived = await mgr.get_session(meta.id)
        assert archived is not None
        assert archived.archived
        assert archived.status is ThreadStatus.ARCHIVED

        await mgr.unarchive(meta.id)
        restored = await mgr.get_session(meta.id)
        assert restored is not None
        assert not restored.archived
        assert restored.archived_at is None
        assert restored.status is ThreadStatus.IDLE
    finally:
        await db.close()
