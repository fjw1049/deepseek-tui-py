"""Registry, origin, and model-catalog hooks."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config import Config
from deepseek_tui.engine.context_pressure import SYNTHETIC_ORIGINS, is_synthetic_user_message
from deepseek_tui.engine.handle import SendMessageOp
from deepseek_tui.engine.reminders import GOAL_CONTINUATION, reminder_message
from deepseek_tui.engine.turn import TurnResult
from deepseek_tui.goal.persist import apply_goal_to_engine
from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.types import (
    GOAL_TOOL_NAMES,
    GOAL_TURN_ID_KEY,
    RESUME_AFTER_RESTORE_REASON,
    GoalStatus,
)
from deepseek_tui.protocol.messages import Message, MessageOrigin
from deepseek_tui.protocol.responses import ToolCall, Usage
from deepseek_tui.server.threads.manager import _engine_mode_for_goal
from deepseek_tui.server.threads.models import GoalCommandRequest
from deepseek_tui.tools.registry import build_default_registry, build_subagent_registry


def test_agent_registry_includes_goal_tools() -> None:
    names = set(build_default_registry(Config(), mode="agent").names())
    assert GOAL_TOOL_NAMES <= names


def test_plan_registry_excludes_goal_tools() -> None:
    names = set(build_default_registry(Config(), mode="plan").names())
    assert not (GOAL_TOOL_NAMES & names)


def test_subagent_registry_never_has_goal_tools() -> None:
    names = set(build_subagent_registry(Config(), mode="agent").names())
    assert not (GOAL_TOOL_NAMES & names)


@pytest.mark.asyncio
async def test_engine_restore_pauses_active_goal(engine_ctx) -> None:
    engine, _handle = engine_ctx
    engine.goal_service.create("Keep going")
    dumped = engine.goal_service.dump()
    apply_goal_to_engine(engine, {"goal": dumped.goal, "goal_queue": dumped.queue})
    snap = engine.goal_service.snapshot()
    assert snap is not None
    assert snap.status is GoalStatus.PAUSED
    assert snap.terminal_reason == RESUME_AFTER_RESTORE_REASON


@pytest.mark.asyncio
async def test_engine_keeps_goal_tool_catalog_stable(engine_ctx) -> None:
    engine, _handle = engine_ctx
    names = {(t.get("function") or t).get("name") for t in await engine._get_tools_with_mcp()}
    assert "CreateGoal" in names
    assert "GetGoal" in names
    assert "UpdateGoal" in names
    assert "SetGoalBudget" in names
    engine.goal_service.create("Ship it")
    after = {(t.get("function") or t).get("name") for t in await engine._get_tools_with_mcp()}
    assert after == names


def test_entering_goal_leaves_plan_and_ask() -> None:
    assert _engine_mode_for_goal("plan") == "agent"
    assert _engine_mode_for_goal("ask") == "agent"
    assert _engine_mode_for_goal("agent") == "agent"
    assert _engine_mode_for_goal("yolo") == "yolo"


def test_continuation_origin_is_synthetic() -> None:
    assert MessageOrigin.GOAL_CONTINUATION in SYNTHETIC_ORIGINS
    msg = reminder_message(GOAL_CONTINUATION, "continue the goal")
    assert msg.origin is MessageOrigin.GOAL_CONTINUATION
    assert is_synthetic_user_message(msg)
    user = Message.user("real request", origin=MessageOrigin.REAL_USER)
    assert not is_synthetic_user_message(user)


@pytest.mark.asyncio
async def test_token_budget_stops_before_tools_execute(engine_ctx) -> None:
    engine, _handle = engine_ctx
    engine.goal_service.create("stay in budget")
    engine.goal_service.set_budget(token_budget=5)
    engine.goal_service.on_turn_started()
    engine.turn_loop.run = AsyncMock(
        return_value=TurnResult(
            assistant_message=Message.assistant(""),
            usage=Usage(input_tokens=10, output_tokens=5),
            tool_calls=[ToolCall(id="call_1", name="read_file", arguments={})],
        )
    )
    engine._execute_tool_calls = AsyncMock(return_value=[])
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)

    result = await engine._run_conversation(
        messages=[Message.user("continue")],
        model="deepseek-chat",
        system_prompt="sys",
        max_tokens=None,
    )

    engine._execute_tool_calls.assert_not_awaited()
    assert result.tool_calls == []
    snapshot = engine.goal_service.snapshot()
    assert snapshot is not None
    assert snapshot.status is GoalStatus.BLOCKED
    assert snapshot.tokens_used == 5


@pytest.mark.asyncio
async def test_create_goal_rejects_stale_replace(engine_ctx) -> None:
    engine, _handle = engine_ctx
    engine.goal_service.create("current")
    engine.tool_context.metadata[GOAL_TURN_ID_KEY] = "stale-goal-id"
    tool = engine.tool_registry.get("CreateGoal")

    result = await tool.execute(
        {"objective": "stale replacement", "replace": True},
        engine.tool_context,
    )

    assert not result.success
    snapshot = engine.goal_service.snapshot()
    assert snapshot is not None
    assert snapshot.objective == "current"


@pytest.mark.asyncio
async def test_create_goal_rejects_goal_added_after_turn_started(engine_ctx) -> None:
    engine, _handle = engine_ctx
    engine.tool_context.metadata[GOAL_TURN_ID_KEY] = None
    engine.goal_service.create("added concurrently")
    tool = engine.tool_registry.get("CreateGoal")

    result = await tool.execute(
        {"objective": "stale replacement", "replace": True},
        engine.tool_context,
    )

    assert not result.success
    assert engine.goal_service.snapshot() is not None
    assert engine.goal_service.snapshot().objective == "added concurrently"


@pytest.mark.asyncio
async def test_runtime_failure_pauses_goal(engine_ctx) -> None:
    engine, _handle = engine_ctx
    engine.goal_service.create("survive failures")
    engine._handle_send_message_inner = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await engine._handle_send_message(SendMessageOp(content="continue"))

    snapshot = engine.goal_service.snapshot()
    assert snapshot is not None
    assert snapshot.status is GoalStatus.PAUSED
    assert "boom" in (snapshot.terminal_reason or "")


@pytest.mark.asyncio
async def test_runtime_promotion_keeps_queue_until_turn_starts(engine_ctx) -> None:
    engine, _handle = engine_ctx
    engine.tool_context.metadata["runtime_thread_id"] = "thread-1"
    engine.goal_service.create("first")
    queued = engine.goal_service.enqueue("second")
    engine.goal_service.mark_complete()

    await engine._finish_goal_turn(
        cancelled=False,
        failed=False,
        error_message=None,
    )

    snapshot = engine.goal_service.snapshot()
    assert snapshot is not None
    assert snapshot.objective == "second"
    assert [item.item_id for item in engine.goal_service.queue_items()] == [
        queued.item_id
    ]
    assert engine.tool_context.metadata["goal_promote_pending"] == {
        "objective": "second",
        "item_id": queued.item_id,
    }


@pytest.mark.asyncio
async def test_goal_reminder_is_not_persisted_in_session_history(engine_ctx) -> None:
    engine, _handle = engine_ctx
    engine.goal_service.create("temporary reminder")
    engine.turn_loop.run = AsyncMock(
        return_value=TurnResult(
            assistant_message=Message.assistant("made progress"),
            usage=Usage(input_tokens=10, output_tokens=2),
            tool_calls=[],
        )
    )
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)

    await engine._handle_send_message_inner(
        SendMessageOp(content="continue"),
        "goal-reminder-turn",
    )

    persisted_text = "\n".join(message.text_content() for message in engine.session_messages)
    assert "active goal (goal mode)" not in persisted_text


async def _goal_command_manager(tmp_path: Path) -> tuple[Any, Any]:
    """Manager + thread pair for /goal command tests (stub LLM client)."""
    from collections.abc import AsyncIterator

    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.config.models import FeatureConfig
    from deepseek_tui.protocol.messages import MessageRequest
    from deepseek_tui.protocol.responses import StreamEvent
    from deepseek_tui.server.threads.manager import RuntimeThreadManager
    from deepseek_tui.server.threads.models import (
        CreateThreadRequest,
        RuntimeThreadManagerConfig,
    )

    class _StubClient(LLMClient):
        async def stream_chat_completion(
            self, request: MessageRequest
        ) -> AsyncIterator[StreamEvent]:
            yield StreamEvent()

    manager = RuntimeThreadManager(
        config=Config(
            features=FeatureConfig(
                mcp=False, tasks=False, subagents=False, automations=False
            )
        ),
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig(
            data_dir=tmp_path / "runtime",
            task_data_dir=tmp_path / "tasks",
        ),
        llm_client=_StubClient(),
    )
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(manager.workspace))
    )
    return manager, thread


@pytest.mark.asyncio
async def test_goal_command_create_rolls_back_when_turn_fails_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """/goal create must not leave an active goal with no running turn."""
    manager, thread = await _goal_command_manager(tmp_path)

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("start_turn failed")

    monkeypatch.setattr(manager, "start_turn", _boom)

    with pytest.raises(RuntimeError, match="start_turn failed"):
        await manager.apply_goal_command(
            thread.id, GoalCommandRequest(args="Ship it")
        )

    state = manager._active.get(thread.id)
    assert state is not None
    snapshot = state.engine.goal_service.snapshot()
    assert snapshot is None, "goal must be cancelled when its first turn cannot start"

    stored = manager.store.load_thread(thread.id)
    assert stored.goal is None

    with contextlib.suppress(asyncio.CancelledError):
        state.engine_task.cancel()
        await state.engine_task


@pytest.mark.asyncio
async def test_goal_command_create_keeps_goal_when_turn_slot_is_busy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """/goal create during a live turn: start_turn is rejected, but the goal
    must survive - the live turn's natural end chains into it via
    _maybe_continue_goal. This mirrors the streaming /goal slash command."""
    from deepseek_tui.server.threads.manager import _ActiveTurnState

    manager, thread = await _goal_command_manager(tmp_path)
    await manager._ensure_engine_loaded(
        manager.store.load_thread(thread.id)
    )
    state = manager._active.get(thread.id)
    assert state is not None

    async with manager._active_lock:
        state.active_turn = _ActiveTurnState(turn_id="turn_live")

    async def _busy(*args: object, **kwargs: object) -> None:
        raise ValueError("Thread already has an active turn")

    monkeypatch.setattr(manager, "start_turn", _busy)

    with pytest.raises(ValueError, match="already has an active turn"):
        await manager.apply_goal_command(
            thread.id, GoalCommandRequest(args="Ship during stream")
        )

    snapshot = state.engine.goal_service.snapshot()
    assert snapshot is not None, "busy turn must not cancel the fresh goal"
    assert snapshot.status is GoalStatus.ACTIVE
    assert snapshot.objective == "Ship during stream"

    stored = manager.store.load_thread(thread.id)
    assert stored.goal is not None

    with contextlib.suppress(asyncio.CancelledError):
        state.engine_task.cancel()
        await state.engine_task


@pytest.mark.asyncio
async def test_goal_command_create_rollback_spares_replaced_goal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If a concurrent replace swapped the goal between create and rollback,
    the rollback must not cancel the newer goal."""
    manager, thread = await _goal_command_manager(tmp_path)
    await manager._ensure_engine_loaded(
        manager.store.load_thread(thread.id)
    )
    state = manager._active.get(thread.id)
    assert state is not None

    async def _boom_then_replace(*args: object, **kwargs: object) -> None:
        state.engine.goal_service.cancel()
        state.engine.goal_service.create("concurrent replacement")
        raise RuntimeError("start_turn failed")

    monkeypatch.setattr(manager, "start_turn", _boom_then_replace)

    with pytest.raises(RuntimeError, match="start_turn failed"):
        await manager.apply_goal_command(
            thread.id, GoalCommandRequest(args="original objective")
        )

    snapshot = state.engine.goal_service.snapshot()
    assert snapshot is not None
    assert snapshot.objective == "concurrent replacement"
    assert snapshot.status is GoalStatus.ACTIVE

    with contextlib.suppress(asyncio.CancelledError):
        state.engine_task.cancel()
        await state.engine_task


@pytest.mark.asyncio
async def test_goal_command_next_add_rolls_back_when_turn_fails_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """/goal next with no current goal starts it - same rollback rule."""
    manager, thread = await _goal_command_manager(tmp_path)

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("start_turn failed")

    monkeypatch.setattr(manager, "start_turn", _boom)

    with pytest.raises(RuntimeError, match="start_turn failed"):
        await manager.apply_goal_command(
            thread.id, GoalCommandRequest(args="next Ship it")
        )

    state = manager._active.get(thread.id)
    assert state is not None
    snapshot = state.engine.goal_service.snapshot()
    assert snapshot is None

    stored = manager.store.load_thread(thread.id)
    assert stored.goal is None

    with contextlib.suppress(asyncio.CancelledError):
        state.engine_task.cancel()
        await state.engine_task


@pytest.mark.asyncio
async def test_tui_goal_resume_skips_manual_launch_while_turn_active() -> None:
    """TUI /goal resume must not queue a second continuation chain while
    a turn is live - the turn's natural end chains the next goal turn."""
    import asyncio

    from deepseek_tui.tui.commands import cmd_goal

    service = GoalService()
    service.create("keep going")
    service.pause()

    launch_calls: list[object] = []

    async def _record_launch() -> bool:
        launch_calls.append(object())
        return True

    engine = SimpleNamespace(
        mode="agent",
        goal_service=service,
        launch_goal_continuation=_record_launch,
        session_messages=[],
    )
    app = SimpleNamespace(
        _engine=engine,
        handle=SimpleNamespace(is_turn_active=lambda: True),
    )

    result = cmd_goal("resume", app)  # type: ignore[arg-type]
    await asyncio.sleep(0)

    assert result.error == ""
    assert service.snapshot() is not None
    assert service.snapshot().status is GoalStatus.ACTIVE
    assert launch_calls == [], "manual continuation must be skipped mid-turn"


@pytest.mark.asyncio
async def test_tui_goal_resume_launches_when_idle() -> None:
    """Idle engine: /goal resume queues exactly one continuation."""
    import asyncio

    from deepseek_tui.tui.commands import cmd_goal

    service = GoalService()
    service.create("keep going")
    service.pause()

    launch_calls: list[object] = []

    async def _record_launch() -> bool:
        launch_calls.append(object())
        return True

    engine = SimpleNamespace(
        mode="agent",
        goal_service=service,
        launch_goal_continuation=_record_launch,
        session_messages=[],
    )
    app = SimpleNamespace(
        _engine=engine,
        handle=SimpleNamespace(is_turn_active=lambda: False),
    )

    result = cmd_goal("resume", app)  # type: ignore[arg-type]
    await asyncio.sleep(0)

    assert result.error == ""
    assert len(launch_calls) == 1
