"""Session-cumulative cache-hit ratio (HANDOVER §九 cache_chip.2026-05-15).

Engine deviates from Rust ``footer_cache_spans`` (ui.rs:7377) here:
where Rust shows ``last_prompt_cache_hit_tokens`` (the most recent
turn's hit count), Python accumulates across the session and emits the
running total in ``TurnCompleteEvent.cache_hit_tokens`` /
``cache_miss_tokens``.

Rationale: DeepSeek's prefix cache means every multi-turn session has
a near-100% per-turn hit ratio, so the Rust per-turn chip is pinned to
~99% and conveys no information. The cumulative ratio actually shows
"how much prompt traffic the cache has saved you so far."
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.events import TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.ops import SendMessageOp
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta, Usage


class _UsageScriptedClient(LLMClient):
    """Yield a scripted sequence of ``Usage`` payloads, one per turn."""

    def __init__(self, usages: list[Usage]) -> None:
        super().__init__()
        self._usages = list(usages)
        self._turn = 0

    async def stream_chat_completion(
        self, request: Any
    ) -> AsyncIterator[StreamTextDelta | StreamDone]:
        idx = min(self._turn, len(self._usages) - 1)
        usage = self._usages[idx]
        self._turn += 1
        yield StreamTextDelta(text="ok")
        yield StreamDone(usage=usage)


async def _drive_turn(engine: Engine, prompt: str) -> TurnCompleteEvent:
    """Send one user message and return the ``TurnCompleteEvent``.

    Drains the event queue concurrently with the engine loop. Bails out
    the moment the target event lands. A 5 s ceiling guards against
    test-runner deadlocks; if it fires the assert message names what
    *was* seen so the failure is debuggable.
    """
    events: list[Any] = []
    done = asyncio.Event()

    async def _drain() -> None:
        # ``engine.handle.events`` is an async-generator factory, not a
        # plain queue — go straight to the underlying queue to avoid
        # spinning up a generator we'd then have to drive.
        while True:
            ev = await engine.handle._event_queue.get()  # noqa: SLF001
            events.append(ev)
            if isinstance(ev, TurnCompleteEvent):
                done.set()

    runner = asyncio.create_task(engine.run())
    drainer = asyncio.create_task(_drain())
    try:
        # Yield once so the runner can install its receive on
        # ``handle.next_op`` before we push.
        await asyncio.sleep(0)
        await engine.handle.send_op(SendMessageOp(content=prompt))
        try:
            await asyncio.wait_for(done.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
    finally:
        runner.cancel()
        drainer.cancel()
        for t in (runner, drainer):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
    matches = [e for e in events if isinstance(e, TurnCompleteEvent)]
    assert matches, (
        "no TurnCompleteEvent emitted; saw "
        f"{[type(e).__name__ for e in events]}"
    )
    return matches[-1]


class TestCumulativeCacheChip:
    @pytest.mark.asyncio
    async def test_engine_starts_with_zero_totals(self, tmp_path: Path) -> None:
        engine = await Engine.create(
            EngineHandle(),
            _UsageScriptedClient([Usage(input_tokens=1, output_tokens=1)]),
            default_model="test",
            working_directory=tmp_path,
        )
        assert engine.session_cache_hit_total == 0
        assert engine.session_cache_miss_total == 0

    @pytest.mark.asyncio
    async def test_cumulative_across_turns(self, tmp_path: Path) -> None:
        """Two turns: hit 60+90, miss 40+10. Final emission carries the
        cumulative 150 / 50."""
        client = _UsageScriptedClient(
            [
                # Turn 1: 60 hit, 40 miss
                Usage(
                    input_tokens=100,
                    output_tokens=10,
                    cache_read_input_tokens=60,
                    cache_creation_input_tokens=40,
                ),
                # Turn 2: 90 hit, 10 miss (typical prefix-cache pattern
                # where almost the entire prompt is reused)
                Usage(
                    input_tokens=100,
                    output_tokens=10,
                    cache_read_input_tokens=90,
                    cache_creation_input_tokens=10,
                ),
            ]
        )
        engine = await Engine.create(
            EngineHandle(),
            client,
            default_model="test",
            working_directory=tmp_path,
        )

        t1 = await _drive_turn(engine, "first")
        assert t1.cache_hit_tokens == 60
        assert t1.cache_miss_tokens == 40
        assert engine.session_cache_hit_total == 60
        assert engine.session_cache_miss_total == 40

        t2 = await _drive_turn(engine, "second")
        # Cumulative, not per-turn — the chip should keep climbing.
        assert t2.cache_hit_tokens == 150
        assert t2.cache_miss_tokens == 50
        assert engine.session_cache_hit_total == 150
        assert engine.session_cache_miss_total == 50

    @pytest.mark.asyncio
    async def test_chip_ratio_reflects_session_not_last_turn(
        self, tmp_path: Path
    ) -> None:
        """A first cold turn (0% hit) plus a warm second turn (90% hit)
        should land between, not at 90%. This is the whole point of the
        cumulative design — Rust's per-turn chip would show 90% the
        instant the cache warms up."""
        client = _UsageScriptedClient(
            [
                # Cold start: nothing in cache.
                Usage(
                    input_tokens=200,
                    output_tokens=10,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=200,
                ),
                # Warm: prefix fully cached.
                Usage(
                    input_tokens=200,
                    output_tokens=10,
                    cache_read_input_tokens=180,
                    cache_creation_input_tokens=20,
                ),
            ]
        )
        engine = await Engine.create(
            EngineHandle(),
            client,
            default_model="test",
            working_directory=tmp_path,
        )

        await _drive_turn(engine, "cold")
        t2 = await _drive_turn(engine, "warm")

        total = t2.cache_hit_tokens + t2.cache_miss_tokens
        pct = 100.0 * t2.cache_hit_tokens / total
        # Cumulative ratio: 180 / 400 = 45%. Rust per-turn would show
        # 180 / (180+20) = 90% on the second turn — different number,
        # different meaning. Verify we are *not* showing the per-turn
        # 90% by checking the value falls in [40, 50].
        assert 40.0 <= pct <= 50.0, f"expected cumulative ~45%, got {pct:.1f}%"

    @pytest.mark.asyncio
    async def test_no_usage_no_accumulation(self, tmp_path: Path) -> None:
        """A turn whose ``Usage`` carries zero cache fields must not
        spuriously bump the totals (a session that never sees cache
        info stays at 0/0 — the status-bar chip hides itself in that
        case)."""
        client = _UsageScriptedClient(
            [Usage(input_tokens=10, output_tokens=10)]
        )
        engine = await Engine.create(
            EngineHandle(),
            client,
            default_model="test",
            working_directory=tmp_path,
        )
        t = await _drive_turn(engine, "noop")
        assert t.cache_hit_tokens == 0
        assert t.cache_miss_tokens == 0
        assert engine.session_cache_hit_total == 0
        assert engine.session_cache_miss_total == 0
