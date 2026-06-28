"""Fork-from-a-point: ``through_item_id`` truncation contract.

The legacy ``fork_thread`` copied the whole thread. The new optional
``through_item_id`` cuts the forked thread at a specific turn item so users can
branch from any message in the timeline.
"""

from __future__ import annotations

from datetime import datetime, timezone

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


async def _make_thread(manager) -> str:
    thread = await manager.create_thread(
        CreateThreadRequest(title="fork-test", workspace=str(manager.workspace))
    )
    return thread.id


async def _seed(manager) -> str:
    thread_id = await _make_thread(manager)
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
async def test_fork_without_criterion_copies_all(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    forked = await manager.fork_thread(thread_id)
    assert forked.id != thread_id
    turns = manager.store.list_turns_for_thread(forked.id)
    assert len(turns) == 2
    messages = reconstruct_messages_from_turns(manager.store, forked.id)
    assert [m.content[0].text for m in messages] == ["Q1", "A1", "Q2", "A2"]


@pytest.mark.asyncio
async def test_fork_through_assistant_message_drops_later_turn(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    forked = await manager.fork_thread(thread_id, through_item_id="item_a1")
    turns = manager.store.list_turns_for_thread(forked.id)
    assert len(turns) == 1
    items = manager.store.list_items_for_turn(turns[0].id)
    assert [i.kind for i in items] == [
        TurnItemKind.USER_MESSAGE,
        TurnItemKind.AGENT_MESSAGE,
    ]
    assert [i.detail for i in items] == ["Q1", "A1"]
    messages = reconstruct_messages_from_turns(manager.store, forked.id)
    assert [m.content[0].text for m in messages] == ["Q1", "A1"]


@pytest.mark.asyncio
async def test_fork_through_user_message_truncates_mid_turn(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    # Fork through the second turn's user message: turn_a fully + turn_b with
    # only the user message (the assistant response is dropped).
    forked = await manager.fork_thread(thread_id, through_item_id="item_u2")
    turns = manager.store.list_turns_for_thread(forked.id)
    assert len(turns) == 2
    items_a = manager.store.list_items_for_turn(turns[0].id)
    items_b = manager.store.list_items_for_turn(turns[1].id)
    assert [i.detail for i in items_a] == ["Q1", "A1"]
    assert [i.detail for i in items_b] == ["Q2"]
    messages = reconstruct_messages_from_turns(manager.store, forked.id)
    assert [m.content[0].text for m in messages] == ["Q1", "A1", "Q2"]


@pytest.mark.asyncio
async def test_fork_unknown_item_raises_value_error(runtime_app) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    with pytest.raises(ValueError):
        await manager.fork_thread(thread_id, through_item_id="item_nope")


@pytest.mark.asyncio
async def test_fork_http_through_item_truncates(
    runtime_app, client: AsyncClient
) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    r = await client.post(
        f"/v1/threads/{thread_id}/fork",
        json={"through_item_id": "item_a1"},
    )
    assert r.status_code == 201
    forked = r.json()
    assert forked["id"] != thread_id
    detail = await client.get(f"/v1/threads/{forked['id']}")
    assert detail.status_code == 200
    body = detail.json()
    # Thread detail carries turns + items; only turn_a's two items survive.
    items = body.get("items", [])
    assert [i["detail"] for i in items] == ["Q1", "A1"]


@pytest.mark.asyncio
async def test_fork_http_unknown_item_returns_400(
    runtime_app, client: AsyncClient
) -> None:
    manager = runtime_app.state.thread_manager
    thread_id = await _seed(manager)

    r = await client.post(
        f"/v1/threads/{thread_id}/fork",
        json={"through_item_id": "item_nope"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_request"
