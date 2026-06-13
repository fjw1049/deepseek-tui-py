"""Monitor turn persists agent segment semantics."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from deepseek_tui.engine.events import (
    AgentRoundCompleteEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
    TurnCompleteEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.agent_segments import AGENT_SEGMENT_KEY, FINAL_ANSWER, MID_TURN_PREFACE
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnRecord,
    _ActiveThreadState,
)
from deepseek_tui.tools.registry import ToolContext


@pytest.mark.asyncio
async def test_monitor_turn_segments_preface_and_terminal_reasoning(runtime_app: object) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
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

    stub_engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")
    async with manager._active_lock:
        manager._active[thread.id] = _ActiveThreadState(handle, stub_engine, engine_task)

    tool = ToolCall(id="tc_seg", name="list_dir", arguments={"path": "src"})

    async def pump() -> None:
        await handle.emit(ThinkingDeltaEvent(thinking="round one reasoning " * 30))
        await handle.emit(TextDeltaEvent(text="开始探索代码库结构。"))
        await handle.emit(ToolCallEvent(tool_call=tool))
        await handle.emit(
            AgentRoundCompleteEvent(
                round_idx=0,
                tool_calls=(tool,),
                preface_text="开始探索代码库结构。",
            )
        )
        await handle.emit(ThinkingDeltaEvent(thinking="(reasoning omitted)\n最终分析报告"))
        await handle.emit(
            AgentRoundCompleteEvent(
                round_idx=1,
                tool_calls=(),
                preface_text=None,
                round_thinking="(reasoning omitted)\n最终分析报告",
            )
        )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
    finally:
        await pump_task
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)

    turn = manager.store.load_turn(turn_id)
    items = [manager.store.load_item(item_id) for item_id in turn.item_ids]
    messages = [item for item in items if item.kind == TurnItemKind.AGENT_MESSAGE]

    assert len(messages) == 2
    preface = next(
        item
        for item in messages
        if isinstance(item.metadata, dict)
        and item.metadata.get(AGENT_SEGMENT_KEY) == MID_TURN_PREFACE
    )
    final = next(
        item
        for item in messages
        if isinstance(item.metadata, dict)
        and item.metadata.get(AGENT_SEGMENT_KEY) == FINAL_ANSWER
    )
    assert preface.detail == "开始探索代码库结构。"
    assert "最终分析报告" in (final.detail or "")
