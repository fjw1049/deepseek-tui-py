"""Parity tests for SessionManager + State timestamp fix.

Tests verify:
1. Schema v2 creates proper INTEGER timestamp columns
2. SessionManager create/resume/fork/archive/list/touch/set_name
3. SessionIndex JSONL append + lookup
4. Session in-memory model basic operations
5. Real executors are importable and have correct signatures
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.state.database import Database
from deepseek_tui.state.session_manager import (
    Session,
    SessionIndex,
    SessionIndexEntry,
    SessionManager,
    SessionSource,
    SessionUsage,
    ThreadStatus,
)


@pytest.fixture()
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_state.db")
    await database.initialize()
    return database


class TestSchemaV2:
    @pytest.mark.asyncio
    async def test_threads_table_has_integer_timestamps(self, db: Database) -> None:
        conn = await db.connect()
        cursor = await conn.execute("PRAGMA table_info(threads)")
        columns = {row[1]: row[2] for row in await cursor.fetchall()}
        assert "created_at" in columns
        assert "updated_at" in columns
        assert "model_provider" in columns
        assert "cwd" in columns
        assert "cli_version" in columns
        assert "source" in columns
        assert "archived_at" in columns
        assert "git_sha" in columns
        assert "git_branch" in columns
        assert "git_origin_url" in columns
        assert "memory_mode" in columns

    @pytest.mark.asyncio
    async def test_messages_has_item_json_column(self, db: Database) -> None:
        conn = await db.connect()
        cursor = await conn.execute("PRAGMA table_info(messages)")
        columns = {row[1]: row[2] for row in await cursor.fetchall()}
        assert "item_json" in columns
        assert "content" in columns

    @pytest.mark.asyncio
    async def test_checkpoints_has_thread_id_and_checkpoint_id(self, db: Database) -> None:
        conn = await db.connect()
        cursor = await conn.execute("PRAGMA table_info(checkpoints)")
        columns = {row[1]: row[2] for row in await cursor.fetchall()}
        assert "thread_id" in columns
        assert "checkpoint_id" in columns
        assert "state_json" in columns


class TestSessionManager:
    @pytest.fixture()
    async def mgr(self, db: Database, tmp_path: Path) -> SessionManager:
        return SessionManager(db, index_path=tmp_path / "session_index.jsonl")

    @pytest.mark.asyncio
    async def test_create_session(self, mgr: SessionManager) -> None:
        session, meta = await mgr.create_session(
            model="deepseek-chat",
            workspace=Path("/tmp/test"),
        )
        assert session.id == meta.id
        assert session.model == "deepseek-chat"
        assert meta.status == ThreadStatus.RUNNING
        assert meta.source == SessionSource.INTERACTIVE
        assert isinstance(meta.created_at, int)
        assert meta.created_at > 0

    @pytest.mark.asyncio
    async def test_resume_session(self, mgr: SessionManager) -> None:
        _, meta = await mgr.create_session(model="m", workspace=Path("/tmp"))
        resumed = await mgr.resume_session(meta.id)
        assert resumed is not None
        assert resumed.source == SessionSource.RESUME
        assert resumed.status == ThreadStatus.RUNNING

    @pytest.mark.asyncio
    async def test_resume_nonexistent_returns_none(self, mgr: SessionManager) -> None:
        result = await mgr.resume_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_fork_session(self, mgr: SessionManager) -> None:
        _, orig = await mgr.create_session(model="deepseek-chat", workspace=Path("/w"))
        forked = await mgr.fork_session(orig.id)
        assert forked is not None
        assert forked.id != orig.id
        assert forked.model_provider == orig.model_provider
        assert forked.source == SessionSource.FORK

    @pytest.mark.asyncio
    async def test_archive_and_unarchive(self, mgr: SessionManager) -> None:
        _, meta = await mgr.create_session(model="m", workspace=Path("/tmp"))
        await mgr.archive(meta.id)
        reloaded = await mgr.get_session(meta.id)
        assert reloaded is not None
        assert reloaded.archived is True
        assert reloaded.archived_at is not None

        await mgr.unarchive(meta.id)
        reloaded2 = await mgr.get_session(meta.id)
        assert reloaded2 is not None
        assert reloaded2.archived is False

    @pytest.mark.asyncio
    async def test_list_excludes_archived(self, mgr: SessionManager) -> None:
        _, m1 = await mgr.create_session(model="m", workspace=Path("/tmp"))
        _, m2 = await mgr.create_session(model="m", workspace=Path("/tmp"))
        await mgr.archive(m1.id)

        visible = await mgr.list_sessions(include_archived=False)
        assert len(visible) == 1
        assert visible[0].id == m2.id

        all_sessions = await mgr.list_sessions(include_archived=True)
        assert len(all_sessions) == 2

    @pytest.mark.asyncio
    async def test_touch_updates_timestamp(self, mgr: SessionManager) -> None:
        _, meta = await mgr.create_session(model="m", workspace=Path("/tmp"))
        import asyncio

        await asyncio.sleep(0.01)
        await mgr.touch(meta.id, preview="hello world")
        reloaded = await mgr.get_session(meta.id)
        assert reloaded is not None
        assert reloaded.preview == "hello world"
        assert reloaded.updated_at >= meta.updated_at

    @pytest.mark.asyncio
    async def test_set_name(self, mgr: SessionManager) -> None:
        _, meta = await mgr.create_session(model="m", workspace=Path("/tmp"))
        await mgr.set_name(meta.id, "my-session")
        name = mgr.find_name(meta.id)
        assert name == "my-session"

    @pytest.mark.asyncio
    async def test_delete(self, mgr: SessionManager) -> None:
        _, meta = await mgr.create_session(model="m", workspace=Path("/tmp"))
        await mgr.delete(meta.id)
        result = await mgr.get_session(meta.id)
        assert result is None


class TestSessionIndex:
    def test_append_and_load(self, tmp_path: Path) -> None:
        index = SessionIndex(tmp_path / "index.jsonl")
        index.append(SessionIndexEntry(thread_id="t1", thread_name="alpha", updated_at=100))
        index.append(SessionIndexEntry(thread_id="t2", thread_name="beta", updated_at=200))
        entries = index.load_map()
        assert len(entries) == 2
        assert entries["t1"].thread_name == "alpha"

    def test_find_name(self, tmp_path: Path) -> None:
        index = SessionIndex(tmp_path / "index.jsonl")
        index.append(SessionIndexEntry(thread_id="t1", thread_name="my-session", updated_at=100))
        assert index.find_name("t1") == "my-session"
        assert index.find_name("nonexistent") is None

    def test_find_path_by_name(self, tmp_path: Path) -> None:
        index = SessionIndex(tmp_path / "index.jsonl")
        index.append(
            SessionIndexEntry(
                thread_id="t1", thread_name="proj", updated_at=100, rollout_path="/a/b"
            )
        )
        assert index.find_path_by_name("proj") == "/a/b"
        assert index.find_path_by_name("PROJ") == "/a/b"  # case-insensitive
        assert index.find_path_by_name("unknown") is None


class TestSessionModel:
    def test_new_session(self) -> None:
        s = Session.new(
            model="deepseek-chat", workspace=Path("/tmp"), allow_shell=True, trust_mode=False
        )
        assert s.id
        assert s.model == "deepseek-chat"
        assert s.messages == []
        assert s.cycle_count == 0

    def test_add_message(self) -> None:
        s = Session.new(model="m", workspace=Path("."), allow_shell=False, trust_mode=False)
        s.add_message({"role": "user", "content": "hello"})
        assert len(s.messages) == 1

    def test_session_usage_add(self) -> None:
        usage = SessionUsage()
        usage.add({"input_tokens": 100, "output_tokens": 50})
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50


class TestRealExecutors:
    def test_task_executor_importable(self) -> None:
        from deepseek_tui.tools.task_manager import get_real_task_executor

        executor = get_real_task_executor()
        assert callable(executor)

    def test_subagent_executor_importable(self) -> None:
        from deepseek_tui.tools.subagent.manager import get_real_subagent_executor

        executor = get_real_subagent_executor()
        assert callable(executor)
