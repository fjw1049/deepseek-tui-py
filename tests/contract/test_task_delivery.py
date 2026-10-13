"""Structured delivery is persisted independently of transport completion."""
import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from deepseek_tui.engine.events import AgentRoundCompleteEvent, TextDeltaEvent, TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.messages import Message
from deepseek_tui.server.threads import CreateThreadRequest, RuntimeTurnStatus, TurnRecord, _ActiveThreadState
from deepseek_tui.tools.registry import ToolContext


async def test_delivery_reaches_transcript_and_turn_record(runtime_app):
    manager = runtime_app.state.thread_manager
    handle = EngineHandle()
    thread = await manager.create_thread(CreateThreadRequest())
    turn_id = "turn_" + uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    manager.store.save_turn(TurnRecord(id=turn_id, thread_id=thread.id,
        status=RuntimeTurnStatus.IN_PROGRESS, input_summary="Read report", created_at=now, started_at=now))
    engine_task = asyncio.create_task(asyncio.Event().wait())
    engine = SimpleNamespace(tool_context=ToolContext(working_directory=manager.workspace))
    manager._active[thread.id] = _ActiveThreadState(handle, engine, engine_task)
    answer = "Total 42. Export remains unavailable."
    outcome = {"status": "partial", "answer": answer, "evidence": ["tool:read"], "remaining": ["Export"]}
    await handle.emit(TextDeltaEvent(text=answer))
    await handle.emit(AgentRoundCompleteEvent(round_idx=2, tool_calls=(), preface_text=answer))
    await handle.emit(TurnCompleteEvent(assistant_message=Message.assistant(answer), task_outcome=outcome))
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
        saved = manager.store.load_turn(turn_id)
        assert saved.status == RuntimeTurnStatus.COMPLETED
        assert saved.task_outcome == outcome
        assert any(manager.store.load_item(i).detail == answer for i in saved.item_ids)
        terminal = [e for e in manager.events_since(thread.id, 0) if e.event == "turn.completed"]
        assert terminal and terminal[-1].payload["turn"]["task_outcome"] == outcome
    finally:
        engine_task.cancel()
        await asyncio.gather(engine_task, return_exceptions=True)
        manager._active.pop(thread.id, None)
