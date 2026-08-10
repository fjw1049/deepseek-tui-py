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
