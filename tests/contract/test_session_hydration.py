"""Engine session hydration from durable runtime thread items."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from deepseek_tui.server.threads import (
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
        from deepseek_tui.tools.registry import ToolContext

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

    monkeypatch.setattr("deepseek_tui.engine.orchestrator.Engine.create", fake_create)

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


def test_reconstruct_drops_interrupted_tools(
    thread_store: RuntimeThreadStore,
) -> None:
    """Soft-resume cuts at the last completed tool-round — drop mid-tool."""
    now = datetime.now(timezone.utc)
    thread_id = "thr_hydrate_interrupt"
    turn_id = "turn_hydrate_interrupt"
    thread_store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.INTERRUPTED,
            input_summary="audit",
            created_at=now,
            started_at=now,
            ended_at=now,
            item_ids=["item_u", "item_tool_ok", "item_tool_orphan"],
        )
    )
    thread_store.save_item(
        TurnItemRecord(
            id="item_u",
            turn_id=turn_id,
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="continue me",
            detail="continue me",
            started_at=now,
            ended_at=now,
        )
    )
    thread_store.save_item(
        TurnItemRecord(
            id="item_tool_ok",
            turn_id=turn_id,
            kind=TurnItemKind.TOOL_CALL,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="list_dir",
            detail="src/",
            metadata={
                "tool_use_id": "call_ok",
                "tool_name": "list_dir",
                "arguments": {"path": "."},
            },
            started_at=now,
            ended_at=now,
        )
    )
    thread_store.save_item(
        TurnItemRecord(
            id="item_tool_orphan",
            turn_id=turn_id,
            kind=TurnItemKind.TOOL_CALL,
            status=TurnItemLifecycleStatus.INTERRUPTED,
            summary="read_file failed: Tool interrupted",
            detail="Tool interrupted",
            metadata={
                "tool_use_id": "call_orphan",
                "tool_name": "read_file",
                "arguments": {"path": "a.py"},
            },
            started_at=now,
            ended_at=now,
        )
    )

    messages = reconstruct_messages_from_turns(thread_store, thread_id)
    assert len(messages) == 3  # user + list_dir use + list_dir result
    assert messages[0].role is Role.USER
    assert messages[1].role is Role.ASSISTANT
    assert messages[1].content[0].id == "call_ok"
    assert messages[2].role is Role.TOOL
    assert messages[2].content[0].tool_use_id == "call_ok"


def test_reconstruct_applies_compaction_snapshot(
    thread_store: RuntimeThreadStore,
) -> None:
    """Compaction snapshot replaces prior history on reconstruct."""
    from deepseek_tui.protocol.messages import Message

    now = datetime.now(timezone.utc)
    thread_id = "thr_hydrate_compact"
    thread_store.save_turn(
        TurnRecord(
            id="turn_old",
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="old",
            created_at=now,
            started_at=now,
            ended_at=now,
            item_ids=["item_old_u"],
        )
    )
    thread_store.save_item(
        TurnItemRecord(
            id="item_old_u",
            turn_id="turn_old",
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="old question",
            detail="old question",
            started_at=now,
            ended_at=now,
        )
    )
    bridge = Message.user("Archived prior context: summary")
    thread_store.save_turn(
        TurnRecord(
            id="turn_compact",
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="compact",
            created_at=now,
            started_at=now,
            ended_at=now,
            item_ids=["item_compact"],
        )
    )
    thread_store.save_item(
        TurnItemRecord(
            id="item_compact",
            turn_id="turn_compact",
            kind=TurnItemKind.CONTEXT_COMPACTION,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="compacted",
            detail="compacted",
            metadata={"session_messages": [bridge.model_dump(mode="json")]},
            started_at=now,
            ended_at=now,
        )
    )

    messages = reconstruct_messages_from_turns(thread_store, thread_id)
    assert len(messages) == 1
    assert messages[0].content[0].text == "Archived prior context: summary"


@pytest.mark.asyncio
async def test_resync_warm_engine_after_interrupted_turn(runtime_app: object) -> None:
    """Interrupt drops in-memory session; durable items must be synced back."""
    from types import SimpleNamespace

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    thread = await manager.create_thread(
        CreateThreadRequest(title="resync", workspace=str(manager.workspace))
    )
    now = datetime.now(timezone.utc)
    turn_id = "turn_resync01"
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.INTERRUPTED,
            input_summary="audit workflow",
            created_at=now,
            started_at=now,
            ended_at=now,
            item_ids=["item_user", "item_tool_ok"],
        )
    )
    manager.store.save_item(
        TurnItemRecord(
            id="item_user",
            turn_id=turn_id,
            kind=TurnItemKind.USER_MESSAGE,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="audit workflow",
            detail="audit workflow",
            started_at=now,
            ended_at=now,
        )
    )
    manager.store.save_item(
        TurnItemRecord(
            id="item_tool_ok",
            turn_id=turn_id,
            kind=TurnItemKind.TOOL_CALL,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="list_dir",
            detail="src/\nREADME.md",
            metadata={
                "tool_use_id": "call_list",
                "tool_name": "list_dir",
                "arguments": {"path": "."},
            },
            started_at=now,
            ended_at=now,
        )
    )

    synced: list[list] = []

    class FakeEngine:
        session_messages: list = []

        def sync_session(self, messages, *, model=None):
            self.session_messages = list(messages)
            synced.append(list(messages))

    engine = FakeEngine()
    manager._active[thread.id] = SimpleNamespace(
        engine=engine, active_turn=None, provider="endpoint"
    )
    try:
        # Simulate post-cancel empty session, then the closeout resync.
        assert engine.session_messages == []
        manager._resync_warm_engine_from_store(thread.id)
    finally:
        manager._active.pop(thread.id, None)

    assert len(synced) == 1
    assert len(synced[0]) == 3  # user + assistant(tool_use) + tool_result
    assert synced[0][0].content[0].text == "audit workflow"
    assert engine.session_messages[2].content[0].tool_use_id == "call_list"
