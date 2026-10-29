"""History rebuilt from persisted items must match what the model saw live."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.events import ToolCallEvent, ToolResultEvent, TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.messages import Role
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadManagerConfig,
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    _ActiveThreadState,
    reconstruct_messages_from_turns,
)
from deepseek_tui.tools.registry import ToolContext


async def _run_tool_turn(manager, workspace: Path, calls) -> str:
    """Drive (ToolCall, content, success) triples through the live persistence path."""
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="test",
            created_at=now,
            started_at=now,
        )
    )
    stub_engine = SimpleNamespace(tool_context=ToolContext(working_directory=workspace))
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)
    ready = asyncio.get_running_loop().create_future()

    async def pump() -> None:
        await asyncio.wait_for(asyncio.shield(ready), timeout=5)
        for call, content, success in calls:
            await handle.emit(ToolCallEvent(tool_call=call))
            await handle.emit(
                ToolResultEvent(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    content=content,
                    success=success,
                )
            )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent", ready)
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)
    return thread.id


@pytest.mark.asyncio
async def test_rebuilt_tool_calls_keep_their_arguments_ids_and_results(
    runtime_app: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    monkeypatch.setattr(manager, "_recover_missing_final_answer", AsyncMock(return_value=None))
    read = ToolCall(id="call_read", name="read_file", arguments={"path": "brief.txt"})
    write = ToolCall(
        id="call_write",
        name="write_file",
        arguments={"path": "notes.md", "content": "# notes\n"},
    )
    refused = "notes.md changed since it was last read; read it again first."
    thread_id = await _run_tool_turn(
        manager,
        tmp_path,
        [(read, "1\tbrief", True), (write, refused, False)],
    )

    messages = reconstruct_messages_from_turns(manager.store, thread_id)
    uses = [b for m in messages if m.role is Role.ASSISTANT for b in m.content
            if getattr(b, "type", None) == "tool_use"]
    results = {b.tool_use_id: b for m in messages if m.role is Role.TOOL for b in m.content}

    assert [(u.id, u.name, u.input) for u in uses] == [
        ("call_read", "read_file", {"path": "brief.txt"}),
        ("call_write", "write_file", {"path": "notes.md", "content": "# notes\n"}),
    ]
    # The model saw the refusal reason live, not a diff of a write that never happened.
    assert results["call_write"].is_error
    assert results["call_write"].content == refused


@pytest.fixture
def thread_store(runtime_data_dir) -> RuntimeThreadStore:
    cfg = RuntimeThreadManagerConfig.from_task_data_dir(runtime_data_dir / "tasks")
    return RuntimeThreadStore(cfg.data_dir)


@pytest.mark.parametrize("source", ["narration_service", "runtime"])
def test_ui_only_progress_text_is_not_replayed_as_model_speech(
    thread_store: RuntimeThreadStore, source: str
) -> None:
    now = datetime.now(timezone.utc)
    thread_id, turn_id = f"thr_{source}", f"turn_{source}"
    thread_store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="q",
            created_at=now,
            started_at=now,
            ended_at=now,
            item_ids=["item_u", "item_ui", "item_model"],
        )
    )
    for item_id, kind, text, meta in [
        ("item_u", TurnItemKind.USER_MESSAGE, "整理资料", None),
        ("item_ui", TurnItemKind.AGENT_MESSAGE, "我会先梳理你的请求。",
         {"process_intent": {"source": source}}),
        ("item_model", TurnItemKind.AGENT_MESSAGE, "已整理完毕。",
         {"process_intent": {"source": "primary_model"}}),
    ]:
        thread_store.save_item(
            TurnItemRecord(
                id=item_id,
                turn_id=turn_id,
                kind=kind,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=text,
                detail=text,
                metadata=meta,
                started_at=now,
                ended_at=now,
            )
        )

    messages = reconstruct_messages_from_turns(thread_store, thread_id)
    assistant_texts = [m.content[0].text for m in messages if m.role is Role.ASSISTANT]
    assert assistant_texts == ["已整理完毕。"]
