"""Regression: ``last_real_input_tokens`` must refresh *within* a turn.

Previously it was only written at turn end (or on cancel), so the /context
panel and the pre-request compaction checks (``should_compact`` / L0 prune /
soft seams — all fed by ``measure_context_pressure(real_input_tokens=...)``)
kept reading the *previous* turn's value while the current turn was still
piling tool results into the context. The fix records each round's
StreamDone usage right after ``turn_loop.run()`` returns.

This test drives ``Engine._run_conversation`` with a fake turn loop and
asserts the signal visible at the start of round 2 is already round 1's
real input_tokens — before the fix it was still 0.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.turn import TurnOutcomeStatus, TurnResult
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall, Usage
from deepseek_tui.tools.runtime import create_tool_runtime

ROUND1_INPUT_TOKENS = 1111
ROUND2_INPUT_TOKENS = 2222


class _FakeTurnLoop:
    """Two canned rounds; snapshots the live pressure signal per round."""

    def __init__(self) -> None:
        self.engine: Engine | None = None
        self.seen_real_input_tokens: list[int] = []
        self._round = 0

    async def run(self, request, emit, cancel_event, **kwargs) -> TurnResult:
        assert self.engine is not None
        self.seen_real_input_tokens.append(self.engine.last_real_input_tokens)
        self._round += 1
        if self._round == 1:
            return TurnResult(
                assistant_message=None,
                usage=Usage(input_tokens=ROUND1_INPUT_TOKENS, output_tokens=10),
                tool_calls=[ToolCall(id="call_1", name="shell", arguments={})],
            )
        return TurnResult(
            assistant_message=Message.assistant("done"),
            usage=Usage(input_tokens=ROUND2_INPUT_TOKENS, output_tokens=5),
            tool_calls=[],
        )


async def test_real_input_tokens_refresh_mid_turn(tmp_path: Path):
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
    fake_loop = _FakeTurnLoop()
    fake_loop.engine = engine
    engine.turn_loop = fake_loop
    engine._execute_tool_calls = AsyncMock(
        return_value=[Message.tool_result("call_1", "ok")]
    )
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
    try:
        result = await engine._run_conversation(
            messages=[Message.user("hi")],
            model="deepseek-chat",
            system_prompt="sys",
            max_tokens=None,
        )

        assert result.outcome == TurnOutcomeStatus.SUCCESS
        # Round 2's pre-request phase (compaction checks, /context reads)
        # already sees round 1's real input_tokens — not the stale 0.
        assert fake_loop.seen_real_input_tokens == [0, ROUND1_INPUT_TOKENS]
        # The final round's usage is recorded before turn end, too.
        assert engine.last_real_input_tokens == ROUND2_INPUT_TOKENS
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()
