"""Rewind audit archive: deleted turns/items land in an append-only JSONL."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig, ProviderConfig
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadManager,
    RuntimeThreadManagerConfig,
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
)
from deepseek_tui.server.threads.rewind_audit import build_rewind_audit_record

THREAD_ID = "thr_audit"


def _seed_thread(
    store: RuntimeThreadStore, thread_id: str = THREAD_ID, turn_count: int = 3
) -> list[TurnRecord]:
    now = datetime.now(timezone.utc)
    turns: list[TurnRecord] = []
    for index in range(turn_count):
        item_id = f"item_{index}"
        store.save_item(
            TurnItemRecord(
                id=item_id,
                turn_id=f"turn_{index}",
                kind=TurnItemKind.USER_MESSAGE,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=f"query {index}",
                detail=f"detail {index}",
                started_at=now + timedelta(seconds=index),
                ended_at=now + timedelta(seconds=index),
            )
        )
        turn = TurnRecord(
            id=f"turn_{index}",
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary=f"query {index}",
            created_at=now + timedelta(seconds=index),
            item_ids=[item_id],
        )
        store.save_turn(turn)
        turns.append(turn)
    return turns


def test_audit_record_archives_only_dropped_turns(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path / "runtime")
    turns = _seed_thread(store)

    record = build_rewind_audit_record(
        store,
        THREAD_ID,
        turns,
        1,
        before_item_id="item_1",
        restore_files=False,
    )

    assert record["thread_id"] == THREAD_ID
    assert record["turns"] == 2
    assert record["items"] == 2
    assert record["fingerprint"]
    snapshot = record["snapshot"]
    assert [entry["turn"]["id"] for entry in snapshot] == ["turn_1", "turn_2"]
    assert [entry["items"][0]["id"] for entry in snapshot] == ["item_1", "item_2"]
    assert snapshot[0]["items"][0]["detail"] == "detail 1"
    assert all("item_0" not in entry["turn"]["item_ids"] for entry in snapshot)


def test_audit_fingerprint_tracks_content(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path / "runtime")
    turns = _seed_thread(store)

    first = build_rewind_audit_record(
        store, THREAD_ID, turns, 1, before_item_id="item_1", restore_files=False
    )
    second = build_rewind_audit_record(
        store, THREAD_ID, turns, 1, before_item_id="item_1", restore_files=False
    )
    turns[1].input_summary = "edited before rewind"
    changed = build_rewind_audit_record(
        store, THREAD_ID, turns, 1, before_item_id="item_1", restore_files=False
    )

    assert first["fingerprint"] == second["fingerprint"]
    assert first["fingerprint"] != changed["fingerprint"]
    assert first["audit_id"] != second["audit_id"]


def test_audit_records_missing_item_as_placeholder(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path / "runtime")
    turns = _seed_thread(store)
    store.delete_item("item_2")

    record = build_rewind_audit_record(
        store, THREAD_ID, turns, 1, before_item_id="item_1", restore_files=False
    )

    dropped_items = record["snapshot"][1]["items"]
    assert dropped_items == [{"id": "item_2", "missing": True}]


def test_rewind_audit_store_roundtrip_and_thread_delete(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path / "runtime")
    record = {"audit_id": "rwa_1", "snapshot": [{"note": "中文"}]}

    store.append_rewind_audit(THREAD_ID, record)
    store.append_rewind_audit(THREAD_ID, {"audit_id": "rwa_2"})
    listed = store.list_rewind_audit(THREAD_ID)
    assert [entry["audit_id"] for entry in listed] == ["rwa_1", "rwa_2"]
    assert listed[0]["snapshot"] == [{"note": "中文"}]

    audit_path = store.root / "rewind_audit" / f"{THREAD_ID}.jsonl"
    audit_path.write_text("{corrupt\n", encoding="utf-8")
    assert store.list_rewind_audit(THREAD_ID) == []

    store.delete_thread(THREAD_ID)
    assert not audit_path.exists()


def _manager(tmp_path: Path) -> RuntimeThreadManager:
    cfg = Config(
        provider="volcengine-ark",
        features=FeatureConfig(
            mcp=False, tasks=False, subagents=False, automations=False
        ),
        providers={
            "volcengine-ark": ProviderConfig(
                api_key="test-key",
                model="glm-5.2",
                base_url="https://ark.example/api/coding/v3",
            )
        },
    )
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    return RuntimeThreadManager(
        config=cfg,
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tasks_dir),
        llm_client=object(),
    )


@pytest.mark.asyncio
async def test_rewind_thread_persists_audit_before_deletion(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    thread = await mgr.create_thread(CreateThreadRequest())
    _seed_thread(mgr.store, thread.id)

    _rewound, _result = await mgr.rewind_thread_with_result(
        thread.id, before_item_id="item_1"
    )

    audits = mgr.store.list_rewind_audit(thread.id)
    assert len(audits) == 1
    record = audits[0]
    assert record["before_item_id"] == "item_1"
    assert record["turns"] == 2
    assert record["items"] == 2
    assert {item["id"] for entry in record["snapshot"] for item in entry["items"]} == {
        "item_1",
        "item_2",
    }

    # The archive holds the full pre-deletion records, not just references.
    assert record["snapshot"][0]["items"][0]["detail"] == "detail 1"

    # The conversation was truncated after the archive was written.
    assert mgr.store.load_turn("turn_0").id == "turn_0"
    with pytest.raises(FileNotFoundError):
        mgr.store.load_turn("turn_1")
    with pytest.raises(FileNotFoundError):
        mgr.store.load_item("item_2")
