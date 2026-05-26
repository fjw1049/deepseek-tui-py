"""Engine session hydration from durable runtime thread items."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from deepseek_tui.app_server.runtime_threads import (
    CreateThreadRequest,
    RuntimeThreadManagerConfig,
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    reconstruct_messages_from_turns,
)
from deepseek_tui.protocol.messages import Role


@pytest.fixture
def thread_store(runtime_data_dir) -> RuntimeThreadStore:
    cfg = RuntimeThreadManagerConfig.from_task_data_dir(runtime_data_dir / "tasks")
    return RuntimeThreadStore(cfg.data_dir)


def test_reconstruct_messages_from_turn_items(thread_store: RuntimeThreadStore) -> None:
    now = datetime.now(timezone.utc)
    thread_id = "thr_hydrate01"
    turn_id = "turn_hydrate01"
    thread_store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="hi",
            created_at=now,
            started_at=now,
            ended_at=now,
        )
    )
    thread_store.save_item(
        TurnItemRecord(
            id="item_user",
            turn_id=turn_id,
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="Hello",
            detail="Hello",
            started_at=now,
            ended_at=now,
        )
    )
    thread_store.save_item(
        TurnItemRecord(
            id="item_asst",
            turn_id=turn_id,
            kind=TurnItemKind.AGENT_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="Hi there",
            detail="Hi there",
            started_at=now,
            ended_at=now,
        )
    )

    messages = reconstruct_messages_from_turns(thread_store, thread_id)
    assert len(messages) == 2
    assert messages[0].role is Role.USER
    assert messages[1].role is Role.ASSISTANT
    assert messages[0].content[0].text == "Hello"
    assert messages[1].content[0].text == "Hi there"


@pytest.mark.asyncio
async def test_ensure_engine_loaded_syncs_session(
    runtime_app: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    captured: dict[str, object] = {}

    async def fake_create(**kwargs: object) -> SimpleNamespace:
        from deepseek_tui.tools.context import ToolContext

        engine = SimpleNamespace(
            tool_context=ToolContext(working_directory=kwargs["working_directory"]),
            session_messages=[],
            sync_session=lambda msgs, *, model=None: captured.update(
                {"messages": list(msgs), "model": model}
            ),
            mode=kwargs.get("mode", "agent"),
            run=lambda: asyncio.sleep(3600),
        )
        return engine

    monkeypatch.setattr("deepseek_tui.engine.engine.Engine.create", fake_create)

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    thread = await manager.create_thread(
        CreateThreadRequest(title="hydrate", workspace=str(manager.workspace))
    )
    now = datetime.now(timezone.utc)
    turn_id = "turn_sync01"
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="q",
            created_at=now,
            started_at=now,
            ended_at=now,
        )
    )
    manager.store.save_item(
        TurnItemRecord(
            id="item_q",
            turn_id=turn_id,
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="What is 2+2?",
            detail="What is 2+2?",
            started_at=now,
            ended_at=now,
        )
    )

    handle, engine_task = await manager._ensure_engine_loaded(thread)
    assert handle is not None
    assert len(captured.get("messages", [])) == 1  # type: ignore[arg-type]
    engine_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await engine_task
    async with manager._active_lock:
        manager._active.pop(thread.id, None)
