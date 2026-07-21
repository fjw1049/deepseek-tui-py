"""A single corrupt/newer-schema record file must not break listings.

Regression coverage for server startup recovery: ``_recover_interrupted_state``
iterates ``list_threads`` / ``list_turns_for_thread``, so one bad JSON file
used to crash the whole server.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from deepseek_tui.server.threads.models import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    ThreadRecord,
    TurnItemRecord,
    TurnRecord,
)
from deepseek_tui.server.threads.store import RuntimeThreadStore


def _thread_record(thread_id: str) -> ThreadRecord:
    now = datetime.now(timezone.utc)
    return ThreadRecord(
        id=thread_id,
        created_at=now,
        updated_at=now,
        model="deepseek-chat",
        workspace="/tmp/ws",
    )


def _turn_record(turn_id: str, thread_id: str) -> TurnRecord:
    return TurnRecord(
        id=turn_id,
        thread_id=thread_id,
        status="completed",
        input_summary="hi",
        created_at=datetime.now(timezone.utc),
    )


def _item_record(item_id: str, turn_id: str) -> TurnItemRecord:
    return TurnItemRecord(
        id=item_id,
        turn_id=turn_id,
        kind="agent_message",
        status="completed",
        summary="done",
    )


def test_list_threads_skips_corrupt_file(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path)
    store.save_thread(_thread_record("good"))
    (tmp_path / "threads" / "bad.json").write_text("{not json", encoding="utf-8")

    threads = store.list_threads()

    assert [t.id for t in threads] == ["good"]


def test_list_threads_skips_newer_schema(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path)
    store.save_thread(_thread_record("good"))
    future = _thread_record("future").model_dump(mode="json")
    future["schema_version"] = CURRENT_RUNTIME_SCHEMA_VERSION + 1
    (tmp_path / "threads" / "future.json").write_text(
        json.dumps(future), encoding="utf-8"
    )

    threads = store.list_threads()

    assert [t.id for t in threads] == ["good"]


def test_list_turns_skips_corrupt_file(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path)
    store.save_turn(_turn_record("good-turn", "t1"))
    (tmp_path / "turns" / "bad.json").write_text("{not json", encoding="utf-8")

    turns = store.list_turns_for_thread("t1")

    assert [t.id for t in turns] == ["good-turn"]


def test_list_items_skips_corrupt_file(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path)
    store.save_item(_item_record("good-item", "turn-1"))
    (tmp_path / "items" / "bad.json").write_text("{not json", encoding="utf-8")

    items = store.list_items_for_turn("turn-1")

    assert [i.id for i in items] == ["good-item"]
