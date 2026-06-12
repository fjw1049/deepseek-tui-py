"""Tests for turn latency helpers and delta batching."""

from __future__ import annotations

import asyncio

import pytest

from deepseek_tui.server.metrics import TurnDeltaBatcher
from deepseek_tui.server.metrics import (
    TurnLatencyTrace,
    first_response_timeout_message,
    first_response_timeout_s,
)


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
    trace.note_tool_exec(40_000)
    segments = trace.segments_ms()
    assert segments["approval_wait_ms"] == 9_600
    assert segments["tool_exec_ms"] == 40_000
    assert segments["agent_loop_ms"] == 49_400


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
