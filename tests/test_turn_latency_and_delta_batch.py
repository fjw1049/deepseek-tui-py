"""Tests for turn latency helpers and delta batching."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from deepseek_tui.server.metrics import (
    TurnDeltaBatcher,
    TurnLatencyTrace,
    bind_turn_latency,
    first_response_timeout_message,
    first_response_timeout_s,
    pop_turn_latency,
)
from deepseek_tui.server.threads.manager import RuntimeThreadManager
from deepseek_tui.server.threads.models import RuntimeTurnStatus, TurnRecord


def test_first_response_timeout_tiers() -> None:
    assert first_response_timeout_s("chat") == 30.0
    assert first_response_timeout_s("ask") == 30.0
    assert first_response_timeout_s("agent") == 120.0
    assert first_response_timeout_s("code") == 120.0
    assert first_response_timeout_s(None) == 120.0


def test_first_response_timeout_message_distinguishes_prep_vs_model() -> None:
    prep = TurnLatencyTrace(turn_id="turn_test")
    assert "准备" in first_response_timeout_message(prep)

    model_wait = TurnLatencyTrace(turn_id="turn_test", llm_request_start_ms=1)
    assert "首包" in first_response_timeout_message(model_wait)


def test_catalog_build_only_records_first_window() -> None:
    trace = TurnLatencyTrace(turn_id="turn_test")
    trace.note_catalog_build(1000, 25, 172)
    trace.note_catalog_build(5000, 300, 172)
    trace.note_catalog_build(9000, 150, 172)

    assert trace.tool_catalog_build_ms == 25
    assert trace.tool_catalog_start_ms == 1000
    assert trace.tool_catalog_end_ms == 1025
    assert trace.catalog_refresh_count == 2
    assert trace.catalog_refresh_total_ms == 450
    assert trace.segments_ms()["first_tool_catalog_ms"] == 25
    assert trace.segments_ms()["catalog_refresh_ms"] == 450


def test_segments_include_approval_tool_exec_and_agent_loop() -> None:
    trace = TurnLatencyTrace(
        turn_id="turn_test",
        runtime_turn_created_ms=1000,
        turn_completed_ms=100_000,
    )
    trace.note_approval_wait(9_600)
    # Per-round tool exec is the wall clock of each (possibly parallel)
    # batch; the segment sums rounds.
    round_trace = trace.start_round(0)
    round_trace.tool_exec_ms = 40_000
    segments = trace.segments_ms()
    assert segments["approval_wait_ms"] == 9_600
    assert segments["tool_exec_ms"] == 40_000
    # agent_loop is the full turn wall clock; tool execution is part of
    # the loop, not subtracted (the old subtraction went negative on
    # parallel-heavy turns and clamped to 0).
    assert segments["agent_loop_ms"] == 99_000


def test_tool_exec_ms_does_not_exceed_end_to_end_for_parallel_calls() -> None:
    """Regression: the reverse-skill turn had ``tool_exec_ms`` (566415)
    exceed ``end_to_end_ms`` (565168) because per-call wall clocks were
    summed, double-counting parallel batches. Summing per-round batch
    wall clocks instead keeps tool_exec within end_to_end."""
    trace = TurnLatencyTrace(
        turn_id="turn_test",
        main_runtime_request_start_ms=0,
        runtime_turn_created_ms=0,
        turn_completed_ms=100_000,
    )
    # Two parallel 60s calls would have summed to 120s under the old
    # per-call tracking. The round records the batch wall clock (60s),
    # which is what segments_ms must use.
    round_trace = trace.start_round(0)
    round_trace.tool_exec_ms = 60_000
    segments = trace.segments_ms()
    assert segments["tool_exec_ms"] == 60_000
    assert segments["end_to_end_ms"] == 100_000
    assert segments["tool_exec_ms"] <= segments["end_to_end_ms"]


def test_round_payload_includes_llm_durations() -> None:
    trace = TurnLatencyTrace(turn_id="turn_test")
    round_trace = trace.start_round(0)
    round_trace.llm_request_start_ms = 100
    round_trace.llm_first_sse_chunk_ms = 828
    round_trace.llm_stream_end_ms = 5000
    round_trace.tool_calls = 3
    round_trace.tool_exec_ms = 12_000

    payload = trace.to_payload()
    assert payload["rounds"][0]["llm_ttfb_ms"] == 728
    assert payload["rounds"][0]["llm_stream_ms"] == 4900
    assert payload["rounds"][0]["tool_calls"] == 3


def test_turn_end_to_end_time_is_frozen_on_the_durable_record(monkeypatch) -> None:
    trace = TurnLatencyTrace(turn_id="turn_elapsed", ui_submit_at_ms=1_000)
    bind_turn_latency(trace)
    monkeypatch.setattr("deepseek_tui.server.threads.manager.now_ms", lambda: 10_000)
    turn = TurnRecord(
        id="turn_elapsed",
        thread_id="thread_elapsed",
        status=RuntimeTurnStatus.COMPLETED,
        input_summary="elapsed",
        created_at=datetime.now(timezone.utc),
        duration_ms=7_000,
    )
    manager = object.__new__(RuntimeThreadManager)
    try:
        payload = manager._finalize_turn_timing(turn)
    finally:
        pop_turn_latency(turn.id)

    assert payload is not None
    assert payload["segments_ms"]["end_to_end_ms"] == 9_000
    assert turn.end_to_end_ms == 9_000


def test_turn_end_to_end_time_falls_back_to_runtime_duration() -> None:
    turn = TurnRecord(
        id="turn_elapsed_fallback",
        thread_id="thread_elapsed",
        status=RuntimeTurnStatus.COMPLETED,
        input_summary="elapsed",
        created_at=datetime.now(timezone.utc),
        duration_ms=7_000,
    )
    manager = object.__new__(RuntimeThreadManager)

    assert manager._finalize_turn_timing(turn) is None
    assert turn.end_to_end_ms == 7_000


@pytest.mark.asyncio
async def test_turn_delta_batcher_coalesces_text() -> None:
    emitted: list[tuple[str, str, dict]] = []

    async def emit(
        thread_id: str,
        turn_id: str,
        item_id: str,
        kind: str,
        payload: dict,
    ) -> None:
        emitted.append((item_id, kind, payload))

    batcher = TurnDeltaBatcher("thread_a", "turn_a", emit)
    await batcher.append("item_1", "agent_message", "hel")
    await batcher.append("item_1", "agent_message", "lo")
    count = await batcher.flush()
    assert count == 1
    assert emitted == [("item_1", "agent_message", {"delta": "hello", "kind": "agent_message"})]


@pytest.mark.asyncio
async def test_turn_delta_batcher_delayed_flush() -> None:
    emitted: list[str] = []

    async def emit(
        thread_id: str,
        turn_id: str,
        item_id: str,
        kind: str,
        payload: dict,
    ) -> None:
        emitted.append(payload["delta"])

    batcher = TurnDeltaBatcher("thread_a", "turn_a", emit)
    await batcher.append("item_1", "agent_message", "a")
    await batcher.append("item_1", "agent_message", "b")
    await asyncio.sleep(0.06)
    assert emitted == ["ab"]


@pytest.mark.asyncio
async def test_turn_delta_batcher_concurrent_flush_during_emit() -> None:
    """Regression: overlapping flush calls must not crash the turn monitor."""
    emitted: list[str] = []
    emit_started = asyncio.Event()

    async def emit(
        thread_id: str,
        turn_id: str,
        item_id: str,
        kind: str,
        payload: dict,
    ) -> None:
        emit_started.set()
        await asyncio.sleep(0.01)
        emitted.append(payload["delta"])

    batcher = TurnDeltaBatcher("thread_a", "turn_a", emit)
    await batcher.append("item_1", "agent_reasoning", "chunk")
    flush_a = asyncio.create_task(batcher.flush())
    await emit_started.wait()
    flush_b = asyncio.create_task(batcher.flush())
    await asyncio.gather(flush_a, flush_b)
    assert emitted == ["chunk"]
