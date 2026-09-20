"""Monitor turn persists agent segment semantics."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
from deepseek_tui.server.agent_segments import (
    AGENT_SEGMENT_KEY,
    FINAL_ANSWER,
    MID_TURN_PREFACE,
)
from deepseek_tui.server.phase_bridge import PROCESS_INTENT_METADATA_KEY
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnRecord,
    _ActiveThreadState,
)
from deepseek_tui.tools.registry import ToolContext


@pytest.mark.asyncio
async def test_monitor_turn_segments_preface_and_terminal_reasoning(
    runtime_app: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    # Final-answer recovery is external to this segmentation contract.
    monkeypatch.setattr(manager, "_recover_missing_final_answer", AsyncMock(return_value=None))
    narrator = AsyncMock(return_value="duplicate progress")
    monkeypatch.setattr(manager, "_compute_phase_bridge", narrator)
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

    # The pre-tool preface is passed through verbatim and tagged with a
    # structured narration frame. Raw reasoning is never promoted to a final
    # answer: with no reachable model for recovery, no final message exists.
    assert len(messages) == 1
    preface = messages[0]
    assert isinstance(preface.metadata, dict)
    assert preface.metadata.get(AGENT_SEGMENT_KEY) == MID_TURN_PREFACE
    assert preface.detail == "开始探索代码库结构。"
    intent = preface.metadata.get(PROCESS_INTENT_METADATA_KEY)
    assert isinstance(intent, dict)
    assert intent["scope"] == "pre_tool"
    assert intent["source"] == "primary_model"
    assert intent["anchors"] == ["src"]
    narrator.assert_not_awaited()


@pytest.mark.asyncio
async def test_monitor_turn_promotes_provisional_text_only_at_turn_end(
    runtime_app: object,
) -> None:
    """No-tool rounds stay mid_turn until TurnComplete promotes the last one."""
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

    tool = ToolCall(id="tc_seg2", name="read_file", arguments={"path": "a.py"})

    async def pump() -> None:
        await handle.emit(TextDeltaEvent(text="先读一下实现。"))
        await handle.emit(ToolCallEvent(tool_call=tool))
        await handle.emit(
            AgentRoundCompleteEvent(
                round_idx=0,
                tool_calls=(tool,),
                preface_text="先读一下实现。",
            )
        )
        # Looks terminal, but orchestrator may still continue (gate/hooks).
        await handle.emit(TextDeltaEvent(text="lint 通过，接着跑 mypy。"))
        await handle.emit(
            AgentRoundCompleteEvent(
                round_idx=1,
                tool_calls=(),
                preface_text="lint 通过，接着跑 mypy。",
            )
        )
        await handle.emit(TextDeltaEvent(text="mypy 是存量问题，本轮到此。"))
        await handle.emit(
            AgentRoundCompleteEvent(
                round_idx=2,
                tool_calls=(),
                preface_text="mypy 是存量问题，本轮到此。",
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
    assert len(messages) == 3

    preface = messages[0]
    assert preface.metadata.get(AGENT_SEGMENT_KEY) == MID_TURN_PREFACE
    assert preface.detail == "先读一下实现。"

    provisional = messages[1]
    assert provisional.metadata.get(AGENT_SEGMENT_KEY) == MID_TURN_PREFACE
    assert provisional.detail == "lint 通过，接着跑 mypy。"

    final = messages[2]
    assert final.metadata.get(AGENT_SEGMENT_KEY) == FINAL_ANSWER
    assert final.detail == "mypy 是存量问题，本轮到此。"


@pytest.mark.asyncio
@pytest.mark.parametrize("superseded", [False, True])
async def test_silent_progress_uses_results_and_discards_late_wording(
    runtime_app: object,
    monkeypatch: pytest.MonkeyPatch,
    superseded: bool,
) -> None:
    from deepseek_tui.engine.events import ToolResultEvent

    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    manager.config.ui.process_narration.min_interval_s = 0
    monkeypatch.setattr(manager, "_recover_missing_final_answer", AsyncMock(return_value=None))
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="修复显示问题",
            created_at=now,
            started_at=now,
        )
    )
    stub = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    idle = asyncio.create_task(asyncio.sleep(3600))
    manager._active[thread.id] = _ActiveThreadState(handle, stub, idle)
    started = asyncio.Event()
    release = asyncio.Event()
    captured: list[dict] = []

    async def compute(**kwargs: object) -> str:
        captured.append(kwargs)
        started.set()
        if superseded:
            await release.wait()
        return "验证发现仍有一处重复，正在检查触发条件。"

    monkeypatch.setattr(manager, "_compute_phase_bridge", compute)
    # Observe persistence, rather than assuming a fixed delay is enough.
    published = asyncio.Event()
    original_emit = manager._emit_event

    async def emit(*args: object, **kwargs: object) -> None:
        await original_emit(*args, **kwargs)
        if any(
            item.detail == "验证发现仍有一处重复，正在检查触发条件。"
            for item in (
                manager.store.load_item(i) for i in manager.store.load_turn(turn_id).item_ids
            )
        ):
            published.set()

    monkeypatch.setattr(manager, "_emit_event", emit)
    tool = ToolCall(id="observed", name="exec_shell", arguments={"command": "verify"})
    next_tool = ToolCall(id="next", name="read_file", arguments={"path": "app.py"})

    async def pump() -> None:
        await handle.emit(TextDeltaEvent(text="正在验证修复是否消除了重复。"))
        await handle.emit(ToolCallEvent(tool_call=tool))
        await handle.emit(
            AgentRoundCompleteEvent(
                round_idx=0, tool_calls=(tool,), preface_text="正在验证修复是否消除了重复。"
            )
        )
        await handle.emit(
            ToolResultEvent(
                tool_call_id=tool.id,
                tool_name=tool.name,
                content="test output\n" * 200 + "1 failed: duplicate row",
                success=False,
            )
        )
        # A model without exposed reasoning still gets evidence-based progress.
        await handle.emit(ToolCallEvent(tool_call=next_tool))
        await handle.emit(AgentRoundCompleteEvent(round_idx=1, tool_calls=(next_tool,)))
        await asyncio.wait_for(started.wait(), 2)
        if not superseded:
            await asyncio.wait_for(published.wait(), 2)
        await handle.emit(TextDeltaEvent(text="重复问题已修复，验证通过。"))
        await handle.emit(
            AgentRoundCompleteEvent(round_idx=2, preface_text="重复问题已修复，验证通过。")
        )
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    pump_task = asyncio.create_task(pump())
    try:
        await asyncio.wait_for(manager._monitor_turn(thread.id, turn_id, handle, "agent"), 5)
        await pump_task
    finally:
        idle.cancel()
        pump_task.cancel()
        await asyncio.gather(idle, pump_task, return_exceptions=True)
        manager._active.pop(thread.id, None)
    assert len(captured) == 1
    observations = captured[0]["recent_tool_results"]
    assert "[failed]" in observations[0]
    assert "1 failed: duplicate row" in observations[0]
    items = [manager.store.load_item(i) for i in manager.store.load_turn(turn_id).item_ids]
    frames = [
        i
        for i in items
        if (i.metadata or {}).get(PROCESS_INTENT_METADATA_KEY, {}).get("source")
        == "narration_service"
    ]
    assert len(frames) == (0 if superseded else 1)
    finals = [i for i in items if (i.metadata or {}).get(AGENT_SEGMENT_KEY) == FINAL_ANSWER]
    assert len(finals) == 1
    assert finals[0].detail == "重复问题已修复，验证通过。"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_tools", [True, False])
@pytest.mark.parametrize("late_preface", ["", "我先核对重复出现的条件，再验证修复。"])
async def test_opening_precedes_silent_tool_batch_and_is_never_duplicated(
    runtime_app: object,
    stream_tools: bool,
    late_preface: str,
) -> None:
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    # The opening does not depend on a secondary model or an enabled narrator.
    manager.config.ui.process_narration.enabled = False
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread.id,
            status=RuntimeTurnStatus.IN_PROGRESS,
            input_summary="修复重复显示",
            created_at=now,
            started_at=now,
        )
    )
    idle = asyncio.create_task(asyncio.sleep(3600))
    stub = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    manager._active[thread.id] = _ActiveThreadState(handle, stub, idle)
    tools = tuple(
        ToolCall(id=f"t{i}", name="read_file", arguments={"path": f"{i}.py"}) for i in range(8)
    )

    async def pump() -> None:
        await handle.emit(ThinkingDeltaEvent(thinking="initial analysis"))
        if stream_tools:
            for tool in tools:
                await handle.emit(ToolCallEvent(tool_call=tool))
        await handle.emit(
            AgentRoundCompleteEvent(round_idx=0, tool_calls=tools, preface_text=late_preface)
        )
        if not stream_tools:
            for tool in tools:
                await handle.emit(ToolCallEvent(tool_call=tool))
        await handle.emit(TextDeltaEvent(text="检查完成。"))
        await handle.emit(AgentRoundCompleteEvent(round_idx=1, preface_text="检查完成。"))
        await handle.emit(TurnCompleteEvent(assistant_message=None))

    producer = asyncio.create_task(pump())
    try:
        await asyncio.wait_for(manager._monitor_turn(thread.id, turn_id, handle, "agent"), 5)
        await producer
    finally:
        idle.cancel()
        producer.cancel()
        await asyncio.gather(idle, producer, return_exceptions=True)
        manager._active.pop(thread.id, None)
    items = [manager.store.load_item(i) for i in manager.store.load_turn(turn_id).item_ids]
    openers = [i for i in items if (i.metadata or {}).get(PROCESS_INTENT_METADATA_KEY)]
    assert len(openers) == 1
    opening = openers[0]
    assert opening.detail == (
        late_preface or "我会先梳理你的请求并核对相关信息，再根据实际结果推进处理。"
    )
    assert opening.metadata[PROCESS_INTENT_METADATA_KEY]["source"] == (
        "primary_model" if late_preface else "runtime"
    )
    assert items.index(opening) < next(
        i for i, item in enumerate(items) if item.kind == TurnItemKind.TOOL_CALL
    )
