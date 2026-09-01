from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from deepseek_tui.server.threads import (
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
)
from deepseek_tui.server.threads.titles import (
    derive_thread_title_from_query,
    first_query_title,
    should_derive_thread_title,
)


def test_derive_thread_title_matches_first_query_display_rules() -> None:
    assert derive_thread_title_from_query("# 修复标题。\n不要改别处") == "修复标题"
    assert derive_thread_title_from_query("/apple-design 做成流动列表") == "做成流动列表"
    assert should_derive_thread_title("新会话", thread_id="thr_12345678") is True
    assert should_derive_thread_title("手动标题", thread_id="thr_12345678") is False


def test_first_query_title_stays_stable_when_later_queries_exist(tmp_path: Path) -> None:
    store = RuntimeThreadStore(tmp_path / "runtime")
    now = datetime.now(timezone.utc)
    queries = ["设计会话标题", "继续"]

    for index, query in enumerate(queries):
        turn_id = f"turn_{index}"
        item_id = f"item_{index}"
        store.save_item(
            TurnItemRecord(
                id=item_id,
                turn_id=turn_id,
                kind=TurnItemKind.USER_MESSAGE,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=query,
                detail=query,
                started_at=now + timedelta(seconds=index),
                ended_at=now + timedelta(seconds=index),
            )
        )
        store.save_turn(
            TurnRecord(
                id=turn_id,
                thread_id="thr_test",
                status=RuntimeTurnStatus.COMPLETED,
                input_summary=query,
                created_at=now + timedelta(seconds=index),
                item_ids=[item_id],
            )
        )

    assert first_query_title(store, "thr_test") == "设计会话标题"
