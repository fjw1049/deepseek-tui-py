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
