"""Tests for host turn lifecycle dispatch helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.capabilities.memory import MEMORY_TURN_CONTEXT_DECORATION, MemoryTurnContext
from deepseek_tui.host.lifecycle import (
    FunctionLifecycleObserver,
    LifecycleRegistry,
    TurnLifecycleResult,
)
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.host.turn_lifecycle import (
    dispatch_after_tool,
    dispatch_before_user_turn,
    dispatch_turn_completed,
    dispatch_turn_failed,
    dispatch_turn_started,
    memory_thread_id_for,
)
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.base import ToolResult


@dataclass
class _FakeEngine:
    memory_thread_id: str | None = "thread-a"
    _cycle_session_id: str | None = None
    tool_context: object = field(default_factory=lambda: MagicMock())
    lifecycle_registry: LifecycleRegistry = field(default_factory=LifecycleRegistry)

    def __post_init__(self) -> None:
        self.tool_context.working_directory = Path("/tmp/workspace")
        self.tool_context.metadata = {}
        self.tool_context.services = ServiceRegistry()


@pytest.mark.asyncio
async def test_memory_thread_id_for_prefers_engine_field() -> None:
    engine = _FakeEngine(memory_thread_id="explicit-thread")
    assert memory_thread_id_for(engine) == "explicit-thread"


@pytest.mark.asyncio
async def test_dispatch_before_user_turn_runs_registry_and_returns_decoration(
    tmp_path: Path,
) -> None:
    engine = _FakeEngine()
    engine.tool_context.working_directory = tmp_path
    observed: list[str] = []

    async def _observe(ctx: object) -> None:
        observed.append("before")
        ctx.decorations[MEMORY_TURN_CONTEXT_DECORATION] = MemoryTurnContext(  # type: ignore[attr-defined]
            thread_id="thread-a",
            recall=None,
            user_message=object(),
        )

    engine.lifecycle_registry.add(
        id="test.before",
        owner="test",
        observer=FunctionLifecycleObserver(on_before_user_turn=_observe),
    )

    result = await dispatch_before_user_turn(
        engine,  # type: ignore[arg-type]
        turn_id="turn-1",
        user_text="hello",
    )

    assert observed == ["before"]
    assert isinstance(result, MemoryTurnContext)
    assert result.thread_id == "thread-a"


@pytest.mark.asyncio
async def test_dispatch_before_user_turn_uses_default_without_observer() -> None:
    engine = _FakeEngine()

    result = await dispatch_before_user_turn(
        engine,  # type: ignore[arg-type]
        turn_id="turn-1",
        user_text="hello",
    )

    assert result.thread_id == "thread-a"
    assert result.recall is None
    assert result.user_message.content[0].text == "hello"


@pytest.mark.asyncio
async def test_dispatch_turn_started_invokes_registry() -> None:
    engine = _FakeEngine()
    mock = AsyncMock()
    engine.lifecycle_registry.on_turn_started = mock

    await dispatch_turn_started(engine, turn_id="turn-2")  # type: ignore[arg-type]

    mock.assert_awaited_once()
    context = mock.await_args.args[0]
    assert context.turn_id == "turn-2"
    assert context.thread_id == "thread-a"


@pytest.mark.asyncio
async def test_dispatch_turn_completed_and_failed() -> None:
    engine = _FakeEngine()

    async def _completed(ctx: object) -> None:
        from deepseek_tui.capabilities.goal import GOAL_TURN_RESULT_DECORATION

        ctx.decorations[GOAL_TURN_RESULT_DECORATION] = TurnLifecycleResult(  # type: ignore[attr-defined]
            steer="done"
        )

    async def _failed(ctx: object) -> None:
        from deepseek_tui.capabilities.goal import GOAL_TURN_RESULT_DECORATION

        ctx.decorations[GOAL_TURN_RESULT_DECORATION] = TurnLifecycleResult()  # type: ignore[attr-defined]

    completed = AsyncMock(side_effect=_completed)
    failed = AsyncMock(side_effect=_failed)
    engine.lifecycle_registry.on_turn_completed = completed
    engine.lifecycle_registry.on_turn_failed = failed

    completed_result = await dispatch_turn_completed(
        engine, turn_id="t1", usage={"tokens": 1}  # type: ignore[arg-type]
    )
    completed.assert_awaited_once()
    assert completed_result.steer == "done"

    failed_result = await dispatch_turn_failed(
        engine, turn_id="t2", reason="boom"  # type: ignore[arg-type]
    )
    failed.assert_awaited_once()
    assert failed_result.follow_up is None
    failure_ctx = failed.await_args.args[0]
    assert failure_ctx.reason == "boom"


@pytest.mark.asyncio
async def test_dispatch_turn_result_uses_default_without_goal_observer() -> None:
    engine = _FakeEngine()

    completed = await dispatch_turn_completed(
        engine, turn_id="t1", usage=None  # type: ignore[arg-type]
    )
    failed = await dispatch_turn_failed(
        engine, turn_id="t2", reason="boom"  # type: ignore[arg-type]
    )

    assert completed == TurnLifecycleResult()
    assert failed == TurnLifecycleResult()


@pytest.mark.asyncio
async def test_dispatch_after_tool_forwards_tool_context() -> None:
    engine = _FakeEngine()
    after_tool = AsyncMock()
    engine.lifecycle_registry.after_tool = after_tool
    tool_call = ToolCall(id="call-1", name="read_file", arguments={"path": "a.txt"})
    result = ToolResult(success=True, content="done")

    await dispatch_after_tool(engine, tool_call, result)  # type: ignore[arg-type]

    after_tool.assert_awaited_once()
    ctx = after_tool.await_args.args[0]
    assert ctx.tool_name == "read_file"
    assert ctx.success is True
