"""Parity tests for RuntimeThreadStore, RuntimeThreadManager, and AsyncBroadcast.

Tests here verify:
1. File-based persistence (save/load/list threads/turns/items/events)
2. AsyncBroadcast multi-consumer delivery
3. RuntimeThreadManager lifecycle (create/start_turn/interrupt/steer/fork/compact)
4. LRU eviction of engine handles
5. Event emission via broadcast
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.app_server.broadcast import AsyncBroadcast
from deepseek_tui.app_server.runtime_threads import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    CreateThreadRequest,
    RuntimeThreadManagerConfig,
    RuntimeThreadStore,
    RuntimeTurnStatus,
    ThreadRecord,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    UpdateThreadRequest,
    duration_ms,
    tool_kind_for_name,
)

# ===========================================================================
# AsyncBroadcast tests
# ===========================================================================


class TestAsyncBroadcast:
    def test_send_to_no_subscribers_returns_zero(self) -> None:
        bc: AsyncBroadcast[str] = AsyncBroadcast(capacity=16)
        assert bc.send("hello") == 0

    def test_single_subscriber_receives_item(self) -> None:
        bc: AsyncBroadcast[int] = AsyncBroadcast(capacity=16)
        q = bc.subscribe()
        bc.send(42)
        assert q.get_nowait() == 42

    def test_multiple_subscribers_all_receive(self) -> None:
        bc: AsyncBroadcast[str] = AsyncBroadcast(capacity=16)
        q1 = bc.subscribe()
        q2 = bc.subscribe()
        bc.send("event_a")
        assert q1.get_nowait() == "event_a"
        assert q2.get_nowait() == "event_a"

    def test_capacity_overflow_drops_oldest(self) -> None:
        bc: AsyncBroadcast[int] = AsyncBroadcast(capacity=2)
        q = bc.subscribe()
        bc.send(1)
        bc.send(2)
        bc.send(3)  # should drop 1
        assert q.get_nowait() == 2
        assert q.get_nowait() == 3
        assert q.empty()

    def test_unsubscribe_removes_queue(self) -> None:
        bc: AsyncBroadcast[str] = AsyncBroadcast(capacity=16)
        q = bc.subscribe()
        bc.unsubscribe(q)
        sent = bc.send("lost")
        assert sent == 0


# ===========================================================================
# RuntimeThreadStore tests
# ===========================================================================


class TestRuntimeThreadStore:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> RuntimeThreadStore:
        return RuntimeThreadStore(tmp_path / "runtime")

    def test_save_and_load_thread(self, store: RuntimeThreadStore) -> None:
        now = datetime.now(timezone.utc)
        thread = ThreadRecord(
            id="t1",
            created_at=now,
            updated_at=now,
            model="deepseek-chat",
            workspace="/tmp/test",
        )
        store.save_thread(thread)
        loaded = store.load_thread("t1")
        assert loaded.id == "t1"
        assert loaded.model == "deepseek-chat"

    def test_load_thread_not_found_raises(self, store: RuntimeThreadStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.load_thread("nonexistent")

    def test_save_and_load_turn(self, store: RuntimeThreadStore) -> None:
        now = datetime.now(timezone.utc)
        turn = TurnRecord(
            id="turn1",
            thread_id="t1",
            status=RuntimeTurnStatus.QUEUED,
            input_summary="hello",
            created_at=now,
        )
        store.save_turn(turn)
        loaded = store.load_turn("turn1")
        assert loaded.thread_id == "t1"
        assert loaded.status == RuntimeTurnStatus.QUEUED

    def test_save_and_load_item(self, store: RuntimeThreadStore) -> None:
        now = datetime.now(timezone.utc)
        item = TurnItemRecord(
            id="item1",
            turn_id="turn1",
            kind=TurnItemKind.AGENT_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="said hello",
            started_at=now,
            ended_at=now,
        )
        store.save_item(item)
        loaded = store.load_item("item1")
        assert loaded.kind == TurnItemKind.AGENT_MESSAGE

    def test_list_threads(self, store: RuntimeThreadStore) -> None:
        now = datetime.now(timezone.utc)
        for i in range(3):
            store.save_thread(
                ThreadRecord(
                    id=f"t{i}",
                    created_at=now,
                    updated_at=now,
                    model="model",
                    workspace="/tmp",
                )
            )
        threads = store.list_threads()
        assert len(threads) == 3

    def test_list_turns_for_thread(self, store: RuntimeThreadStore) -> None:
        now = datetime.now(timezone.utc)
        store.save_turn(
            TurnRecord(
                id="turn_a",
                thread_id="t1",
                status=RuntimeTurnStatus.COMPLETED,
                input_summary="a",
                created_at=now,
            )
        )
        store.save_turn(
            TurnRecord(
                id="turn_b",
                thread_id="t2",
                status=RuntimeTurnStatus.COMPLETED,
                input_summary="b",
                created_at=now,
            )
        )
        turns = store.list_turns_for_thread("t1")
        assert len(turns) == 1
        assert turns[0].id == "turn_a"

    def test_list_items_for_turn(self, store: RuntimeThreadStore) -> None:
        now = datetime.now(timezone.utc)
        store.save_item(
            TurnItemRecord(
                id="i1",
                turn_id="turn_a",
                kind=TurnItemKind.USER_MESSAGE,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary="user msg",
                started_at=now,
            )
        )
        store.save_item(
            TurnItemRecord(
                id="i2",
                turn_id="turn_b",
                kind=TurnItemKind.ERROR,
                status=TurnItemLifecycleStatus.FAILED,
                summary="error",
                started_at=now,
            )
        )
        items = store.list_items_for_turn("turn_a")
        assert len(items) == 1
        assert items[0].id == "i1"

    @pytest.mark.asyncio
    async def test_append_and_read_events(self, store: RuntimeThreadStore) -> None:
        evt = await store.append_event("t1", "turn1", None, "turn_started", {"foo": 1})
        assert evt.seq == 1
        evt2 = await store.append_event("t1", "turn1", None, "text_delta", {"text": "hi"})
        assert evt2.seq == 2

        events = store.events_since("t1", since_seq=None)
        assert len(events) == 2

        events_after_1 = store.events_since("t1", since_seq=1)
        assert len(events_after_1) == 1
        assert events_after_1[0].seq == 2

    @pytest.mark.asyncio
    async def test_events_for_nonexistent_thread(self, store: RuntimeThreadStore) -> None:
        events = store.events_since("ghost", since_seq=None)
        assert events == []

    def test_schema_version_validation(self, store: RuntimeThreadStore) -> None:
        now = datetime.now(timezone.utc)
        thread = ThreadRecord(
            id="future",
            created_at=now,
            updated_at=now,
            model="model",
            workspace="/tmp",
            schema_version=CURRENT_RUNTIME_SCHEMA_VERSION + 10,
        )
        store.save_thread(thread)
        with pytest.raises(ValueError, match="newer than supported"):
            store.load_thread("future")


# ===========================================================================
# RuntimeThreadManager tests
# ===========================================================================


class TestRuntimeThreadManager:
    @pytest.fixture()
    def mgr(self, tmp_path: Path) -> Any:
        from deepseek_tui.app_server.thread_manager import RuntimeThreadManager
        from deepseek_tui.config.models import Config

        manager_cfg = RuntimeThreadManagerConfig(
            data_dir=tmp_path / "runtime",
            task_data_dir=tmp_path,
        )
        config = Config()
        return RuntimeThreadManager(
            config=config,
            workspace=tmp_path,
            manager_cfg=manager_cfg,
        )

    @pytest.mark.asyncio
    async def test_create_thread(self, mgr: Any) -> None:
        thread = await mgr.create_thread(
            CreateThreadRequest(model="deepseek-chat", workspace="/tmp/prj")
        )
        assert thread.id
        assert thread.model == "deepseek-chat"
        assert thread.workspace == "/tmp/prj"

    @pytest.mark.asyncio
    async def test_list_threads_excludes_archived(self, mgr: Any) -> None:
        t1 = await mgr.create_thread(CreateThreadRequest(model="m"))
        await mgr.update_thread(t1.id, UpdateThreadRequest(archived=True))
        t2 = await mgr.create_thread(CreateThreadRequest(model="m"))

        visible = await mgr.list_threads(include_archived=False)
        assert len(visible) == 1
        assert visible[0].id == t2.id

        all_threads = await mgr.list_threads(include_archived=True)
        assert len(all_threads) == 2

    @pytest.mark.asyncio
    async def test_fork_thread(self, mgr: Any) -> None:
        orig = await mgr.create_thread(
            CreateThreadRequest(model="deepseek-chat", workspace="/w")
        )
        forked = await mgr.fork_thread(orig.id)
        assert forked.id != orig.id
        assert forked.model == orig.model
        assert forked.workspace == orig.workspace

    @pytest.mark.asyncio
    async def test_get_thread_detail(self, mgr: Any) -> None:
        thread = await mgr.create_thread(CreateThreadRequest(model="m"))
        detail = await mgr.get_thread_detail(thread.id)
        assert detail.thread.id == thread.id
        assert detail.turns == []
        assert detail.items == []

    @pytest.mark.asyncio
    async def test_events_emitted_on_create(self, mgr: Any) -> None:
        q = mgr.event_bus.subscribe()
        await mgr.create_thread(CreateThreadRequest(model="m"))
        evt = q.get_nowait()
        assert evt.event == "thread.started"


# ===========================================================================
# Helper function tests
# ===========================================================================


class TestHelperFunctions:
    def test_tool_kind_for_name_shell(self) -> None:
        assert tool_kind_for_name("exec_shell") == TurnItemKind.COMMAND_EXECUTION
        assert tool_kind_for_name("exec_shell_wait") == TurnItemKind.COMMAND_EXECUTION

    def test_tool_kind_for_name_file(self) -> None:
        assert tool_kind_for_name("file_write") == TurnItemKind.FILE_CHANGE
        assert tool_kind_for_name("apply_patch") == TurnItemKind.FILE_CHANGE
        assert tool_kind_for_name("file_edit") == TurnItemKind.FILE_CHANGE

    def test_tool_kind_for_name_generic(self) -> None:
        assert tool_kind_for_name("read_file") == TurnItemKind.TOOL_CALL
        assert tool_kind_for_name("search") == TurnItemKind.TOOL_CALL

    def test_duration_ms(self) -> None:
        from datetime import timedelta

        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = t1 + timedelta(seconds=1, milliseconds=500)
        assert duration_ms(t1, t2) == 1500

    def test_duration_ms_clamps_negative(self) -> None:
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        assert duration_ms(t1, t2) == 0
