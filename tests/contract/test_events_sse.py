from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from deepseek_tui.app_server.runtime_api.sse import runtime_event_payload, stream_thread_events
from deepseek_tui.app_server.runtime_threads import (
    CreateThreadRequest,
    RuntimeEventRecord,
)


def test_runtime_event_payload_shape() -> None:
    record = RuntimeEventRecord(
        seq=1,
        timestamp=datetime.now(timezone.utc),
        thread_id="thr_test",
        turn_id="turn_test",
        item_id="item_test",
        event="item.delta",
        payload={"delta": "hi", "kind": "agent_message"},
    )
    payload = runtime_event_payload(record)
    assert payload["seq"] == 1
    assert payload["event"] == "item.delta"
    assert payload["payload"]["kind"] == "agent_message"


@pytest.mark.asyncio
async def test_stream_thread_events_replays_backlog(runtime_app: object) -> None:
    """Generator-level SSE contract (mirrors what HTTP stream would emit)."""
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    thread = await manager.create_thread(CreateThreadRequest())
    gen = stream_thread_events(manager, thread.id, since_seq=None)

    first = await asyncio.wait_for(gen.__anext__(), timeout=3.0)
    assert "event: thread.started" in first
    assert "data:" in first

    await gen.aclose()


@pytest.mark.asyncio
async def test_stream_subscribes_before_reading_backlog(runtime_app: object) -> None:
    """Events emitted between backlog read and live subscribe must not be lost.

    Regression for the original ordering bug where ``subscribe_events`` ran
    *after* ``events_since``: events landing in that window fell into neither
    path. We simulate the race by emitting an event after the generator is
    constructed but before its first ``__anext__`` await.
    """
    manager = runtime_app.state.thread_manager  # type: ignore[attr-defined]
    thread = await manager.create_thread(CreateThreadRequest())
    detail = await manager.get_thread_detail(thread.id)
    cursor = detail.latest_seq

    gen = stream_thread_events(manager, thread.id, since_seq=cursor)
    # Emit *after* generator is built; with subscribe-first this lands in the
    # live queue. Without the fix the event would be silently dropped.
    await manager._emit_event(  # type: ignore[attr-defined]
        thread.id, None, None, "thread.test_race", {"marker": True}
    )

    frame = await asyncio.wait_for(gen.__anext__(), timeout=3.0)
    assert "event: thread.test_race" in frame
    await gen.aclose()
