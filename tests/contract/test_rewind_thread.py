"""Rewind-in-place: ``before_item_id`` truncation contract.

Backs the Workbench "edit & resend" flow: rewinding a thread deletes the
target item and everything after it from the durable store (unlike fork,
which clones into a new thread), so a later reload cannot resurrect the
dropped turns. A warm engine session is re-synced to the truncated history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    reconstruct_messages_from_turns,
)


def _add_turn(
    manager,
    *,
    thread_id: str,
    turn_id: str,
    offset: int,
    user_id: str,
    user_text: str,
    asst_id: str,
    asst_text: str,
) -> None:
    ts = datetime(2020, 1, 1, offset, tzinfo=timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary=user_text,
            created_at=ts,
            started_at=ts,
            ended_at=ts,
            item_ids=[user_id, asst_id],
        )
    )
    for item_id, kind, text in (
        (user_id, TurnItemKind.USER_MESSAGE, user_text),
        (asst_id, TurnItemKind.AGENT_MESSAGE, asst_text),
    ):
        manager.store.save_item(
            TurnItemRecord(
                id=item_id,
                turn_id=turn_id,
                kind=kind,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=text,
                detail=text,
                started_at=ts,
                ended_at=ts,
            )
        )


async def _seed(manager) -> str:
    thread = await manager.create_thread(
        CreateThreadRequest(title="rewind-test", workspace=str(manager.workspace))
    )
    thread_id = thread.id
    _add_turn(
        manager,
        thread_id=thread_id,
        turn_id="turn_a",
        offset=1,
        user_id="item_u1",
        user_text="Q1",
        asst_id="item_a1",
        asst_text="A1",
    )
    _add_turn(
        manager,
        thread_id=thread_id,
        turn_id="turn_b",
        offset=2,
        user_id="item_u2",
        user_text="Q2",
        asst_id="item_a2",
        asst_text="A2",
    )
    return thread_id


@pytest.mark.asyncio
async def test_rewind_at_user_message_deletes_turn_and_after(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    thread = await manager.rewind_thread(thread_id, before_item_id="item_u2")

    turns = manager.store.list_turns_for_thread(thread_id)
    assert [t.id for t in turns] == ["turn_a"]
    assert thread.latest_turn_id == "turn_a"
    messages = reconstruct_messages_from_turns(manager.store, thread_id)
    assert [m.content[0].text for m in messages] == ["Q1", "A1"]
    # Item files for the dropped turn are gone, not just unreferenced.
    with pytest.raises(FileNotFoundError):
        manager.store.load_item("item_u2")
    with pytest.raises(FileNotFoundError):
        manager.store.load_item("item_a2")
    with pytest.raises(FileNotFoundError):
        manager.store.load_turn("turn_b")


@pytest.mark.asyncio
async def test_rewind_mid_turn_keeps_earlier_items(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    await manager.rewind_thread(thread_id, before_item_id="item_a1")

    turns = manager.store.list_turns_for_thread(thread_id)
    assert [t.id for t in turns] == ["turn_a"]
    items = manager.store.list_items_for_turn("turn_a")
    assert [i.detail for i in items] == ["Q1"]
    messages = reconstruct_messages_from_turns(manager.store, thread_id)
    assert [m.content[0].text for m in messages] == ["Q1"]


@pytest.mark.asyncio
async def test_rewind_at_first_item_empties_thread(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    thread = await manager.rewind_thread(thread_id, before_item_id="item_u1")

    assert manager.store.list_turns_for_thread(thread_id) == []
    assert thread.latest_turn_id is None
    assert reconstruct_messages_from_turns(manager.store, thread_id) == []


@pytest.mark.asyncio
async def test_rewind_resyncs_warm_engine_session(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    synced: list[list] = []

    class FakeEngine:
        def sync_session(self, messages, *, model=None):
            synced.append(list(messages))

    manager._active[thread_id] = SimpleNamespace(
        engine=FakeEngine(), active_turn=None
    )
    try:
        await manager.rewind_thread(thread_id, before_item_id="item_u2")
    finally:
        manager._active.pop(thread_id, None)

    assert len(synced) == 1
    assert [m.content[0].text for m in synced[0]] == ["Q1", "A1"]


@pytest.mark.asyncio
async def test_rewind_rejected_while_turn_active(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    manager._active[thread_id] = SimpleNamespace(
        engine=None, active_turn=object()
    )
    try:
        with pytest.raises(ValueError):
            await manager.rewind_thread(thread_id, before_item_id="item_u2")
    finally:
        manager._active.pop(thread_id, None)

    # Nothing was deleted.
    turns = manager.store.list_turns_for_thread(thread_id)
    assert [t.id for t in turns] == ["turn_a", "turn_b"]


@pytest.mark.asyncio
async def test_rewind_unknown_item_raises_value_error(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    with pytest.raises(ValueError):
        await manager.rewind_thread(thread_id, before_item_id="item_nope")


@pytest.mark.asyncio
async def test_rewind_http_truncates_in_place(
    runtime_app, client: AsyncClient
) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    r = await client.post(
        f"/v1/threads/{thread_id}/rewind",
        json={"before_item_id": "item_u2"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == thread_id

    detail = await client.get(f"/v1/threads/{thread_id}")
    assert detail.status_code == 200
    items = detail.json().get("items", [])
    assert [i["detail"] for i in items] == ["Q1", "A1"]


@pytest.mark.asyncio
async def test_rewind_http_unknown_item_returns_400(
    runtime_app, client: AsyncClient
) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    r = await client.post(
        f"/v1/threads/{thread_id}/rewind",
        json={"before_item_id": "item_nope"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_request"
