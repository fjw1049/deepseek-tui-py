"""Turn facts are shown below the answer and stay out of model history."""
import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from deepseek_tui.engine.events import AgentRoundCompleteEvent, TextDeltaEvent, TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.messages import Message
from deepseek_tui.server.threads import CreateThreadRequest, RuntimeTurnStatus, TurnRecord, _ActiveThreadState
from deepseek_tui.server.threads.items import reconstruct_messages_from_turns
from deepseek_tui.tools.registry import ToolContext


async def test_note_reaches_the_user_but_not_the_models_history(runtime_app):
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
    outcome = {"status": "partial", "remaining": ["exec_shell export"]}
    note = "---\n**核验状态**（系统生成）\n- 未解决的工具失败：exec_shell export: boom"
    await handle.emit(TextDeltaEvent(text=answer))
    await handle.emit(AgentRoundCompleteEvent(round_idx=2, tool_calls=(), preface_text=answer))
    await handle.emit(TurnCompleteEvent(
        assistant_message=Message.assistant(answer), task_outcome=outcome, completion_note=note))
    try:
        await manager._monitor_turn(thread.id, turn_id, handle, "agent")
        saved = manager.store.load_turn(turn_id)
        assert saved.status == RuntimeTurnStatus.COMPLETED
        assert saved.task_outcome == outcome
        shown = [manager.store.load_item(i) for i in saved.item_ids]
        assert any(item.detail == f"{answer}\n\n{note}" for item in shown)
        history = reconstruct_messages_from_turns(manager.store, thread.id)
        assert [m.text_content() for m in history if m.role.value == "assistant"] == [answer]
        terminal = [e for e in manager.events_since(thread.id, 0) if e.event == "turn.completed"]
        assert terminal and terminal[-1].payload["turn"]["task_outcome"] == outcome
    finally:
        engine_task.cancel()
        await asyncio.gather(engine_task, return_exceptions=True)
        manager._active.pop(thread.id, None)
