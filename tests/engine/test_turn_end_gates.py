"""Turn-end gates that must not be skipped or spin forever.

Two regressions, both in the ``not result.tool_calls`` branch of
``Engine._run_conversation``:

1. Steers are drained only at the top of a round. Text queued after the last
   drain — the user typing while the final answer streams — used to be
   stranded: ``steer_turn`` had already persisted it as a COMPLETED user
   message, but no round was left to read it, so the model never saw it.
2. ``turn_end`` hooks had no fire cap on the engine side. A hook that blocks
   unconditionally spun to ``max_tool_round_trips``, re-sending the whole
   context every round, before failing the turn.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.orchestrator.core import _STOP_HOOK_MAX_FIRES
from deepseek_tui.engine.turn import TurnResult
from deepseek_tui.integrations.hooks import HookResult
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import build_default_registry
from deepseek_tui.tools.runtime import create_tool_runtime


async def _engine(tmp_path: Path) -> tuple[Engine, EngineHandle, object]:
    cfg = Config(
        features=FeatureConfig(
            tasks=True,
            subagents=True,
            mcp=False,  # avoid hanging MCP handshakes in tests
            automations=False,
        ),
    )
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
        mode="agent",
        task_data_dir=tmp_path / ".deepseek" / "tasks",
        start_mcp=False,
    )
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=cfg,
        working_directory=tmp_path,
        tool_runtime=runtime,
    )
    # Nothing here exercises sub-agent handoff; keep the turn from waiting.
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
    return engine, handle, runtime


class _SteerWhileAnsweringLoop:
    """Never calls a tool; the user types during the first round."""

    def __init__(self, handle: EngineHandle) -> None:
        self.handle = handle
        self.rounds: list[list[str]] = []

    async def run(self, request, emit, cancel_event, **kwargs) -> TurnResult:
        self.rounds.append([m.text_content() for m in request.messages])
        if len(self.rounds) == 1:
            # The drain for this round already happened, and this round has no
            # tool calls — so nothing is left to pick the steer up.
            await self.handle.steer("stop installing, use pnpm")
        return TurnResult(
            assistant_message=Message.assistant("done"),
            usage=None,
            tool_calls=[],
        )


async def test_turn_does_not_end_while_a_steer_is_still_queued(tmp_path: Path) -> None:
    engine, handle, runtime = await _engine(tmp_path)
    loop = _SteerWhileAnsweringLoop(handle)
    engine.turn_loop = loop
    try:
        await engine._run_conversation(
            messages=[Message.user("install the deps")],
            model="deepseek-chat",
            system_prompt="sys",
            max_tokens=None,
        )

        # One extra round, and the queued steer is in what the model reads.
        assert len(loop.rounds) == 2
        assert any("pnpm" in text for text in loop.rounds[1])
        # Consumed, not left behind for some later turn to replay out of order.
        assert not handle.has_pending_steers()
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()


class _CountingLoop:
    """Never calls a tool, so every round reaches the turn-end gates."""

    def __init__(self) -> None:
        self.rounds = 0

    async def run(self, request, emit, cancel_event, **kwargs) -> TurnResult:
        self.rounds += 1
        return TurnResult(
            assistant_message=Message.assistant("done"),
            usage=None,
            tool_calls=[],
        )


async def test_blocking_turn_end_hook_gives_up_before_the_round_trip_limit(
    tmp_path: Path,
) -> None:
    engine, handle, runtime = await _engine(tmp_path)
    loop = _CountingLoop()
    engine.turn_loop = loop
    # A hook that blocks the stop unconditionally, forever.
    engine.hook_executor.has_hooks_for_event = lambda event: event == "turn_end"

    async def _always_block(event, ctx=None, **kwargs):
        if event != "turn_end":
            return []
        return [
            HookResult(
                name="stubborn",
                success=False,
                blocked=True,
                block_reason="not done yet",
            )
        ]

    engine._run_lifecycle_hook = _always_block
    # Well below the real default (200) so a missing cap is unmistakable.
    engine.max_tool_round_trips = 10
    try:
        await engine._run_conversation(
            messages=[Message.user("hi")],
            model="deepseek-chat",
            system_prompt="sys",
            max_tokens=None,
        )

        # Blocks _STOP_HOOK_MAX_FIRES times, then the turn is allowed to end —
        # it does not walk to the round-trip limit.
        assert loop.rounds == _STOP_HOOK_MAX_FIRES + 1
        assert loop.rounds < engine.max_tool_round_trips
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()


class _ScriptedLoop:
    def __init__(self, script: list[TurnResult]) -> None:
        self.script = script
        self.rounds = 0

    async def run(self, request, emit, cancel_event, **kwargs) -> TurnResult:
        step = self.script[self.rounds]
        self.rounds += 1
        return step


async def _seed_checklist(engine: Engine, todos: list[dict]) -> None:
    registry = build_default_registry(mode="agent")
    await registry.execute("checklist", {"todos": todos}, engine.tool_context)


async def _apply_tools(engine: Engine, tool_calls: list[ToolCall], model=None):
    registry = build_default_registry(mode="agent")
    results = []
    for tc in tool_calls:
        if tc.name == "checklist":
            executed = await registry.execute(
                "checklist", tc.arguments, engine.tool_context
            )
            content = executed.content
        else:
            content = "ok"
        results.append(Message.tool_result(tc.id, content))
    return results


async def test_done_stop_is_kept_when_checklist_is_only_reconciled(
    tmp_path: Path,
) -> None:
    engine, handle, runtime = await _engine(tmp_path)
    await _seed_checklist(engine, [{"content": "research", "status": "in_progress"}])
    report = Message.assistant("here is the full workflow report")
    loop = _ScriptedLoop(
        [
            TurnResult(assistant_message=report, tool_calls=[]),
            TurnResult(
                assistant_message=Message.assistant(""),
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="checklist",
                        arguments={"op": "update", "id": "1", "status": "completed"},
                    )
                ],
            ),
            TurnResult(
                assistant_message=Message.assistant("please give me your task"),
                tool_calls=[],
            ),
        ]
    )
    engine.turn_loop = loop
    engine._execute_tool_calls = lambda calls, model=None: _apply_tools(
        engine, calls, model
    )
    try:
        result = await engine._run_conversation(
            messages=[Message.user("research the workflow")],
            model="deepseek-chat",
            system_prompt="sys",
            max_tokens=None,
        )

        # Tracking closed the list. Do not generate a replacement answer.
        assert loop.rounds == 2
        assert result.assistant_message is report
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()


async def test_open_checklist_after_stop_keeps_working(tmp_path: Path) -> None:
    engine, handle, runtime = await _engine(tmp_path)
    await _seed_checklist(engine, [{"content": "implement foo", "status": "pending"}])
    loop = _ScriptedLoop(
        [
            TurnResult(
                assistant_message=Message.assistant("looking into it"),
                tool_calls=[],
            ),
            TurnResult(
                assistant_message=Message.assistant(""),
                tool_calls=[
                    ToolCall(
                        id="r1",
                        name="read_file",
                        arguments={"path": "src/foo.py"},
                    )
                ],
            ),
            TurnResult(
                assistant_message=Message.assistant("implemented foo"),
                tool_calls=[],
            ),
        ]
    )
    engine.turn_loop = loop
    engine._execute_tool_calls = lambda calls, model=None: _apply_tools(
        engine, calls, model
    )
    try:
        result = await engine._run_conversation(
            messages=[Message.user("implement foo")],
            model="deepseek-chat",
            system_prompt="sys",
            max_tokens=None,
        )

        # The first stop was premature: a real tool ran, so the loop continued.
        assert loop.rounds == 3
        assert result.assistant_message is not None
        assert result.assistant_message.text_content() == "implemented foo"
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()
