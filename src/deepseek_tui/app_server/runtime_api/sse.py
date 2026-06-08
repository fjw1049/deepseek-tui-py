"""SSE helpers for runtime thread events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.app_server.runtime_threads import RuntimeEventRecord
    from deepseek_tui.app_server.thread_manager import RuntimeThreadManager


def runtime_event_payload(record: RuntimeEventRecord) -> dict[str, object]:
    """Mirror Rust ``runtime_event_payload`` (runtime_api.rs)."""
    return {
        "seq": record.seq,
        "timestamp": record.timestamp.isoformat(),
        "thread_id": record.thread_id,
        "turn_id": record.turn_id,
        "item_id": record.item_id,
        "event": record.event,
        "payload": record.payload,
    }


def sse_frame(event_name: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, default=str)
    return f"event: {event_name}\ndata: {data}\n\n"


async def stream_thread_events(
    manager: RuntimeThreadManager,
    thread_id: str,
    since_seq: int | None,
    *,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[str]:
    """Replay backlog then live events from ``event_bus``.

    Subscription happens *before* reading backlog so events emitted between
    the two reads land in the live queue rather than being silently dropped
    (mirrors Rust runtime_api.rs:1305-1349 ordering).
    Duplicate events arriving via both paths are filtered by ``last_seq``.
    """
    queue = manager.subscribe_events()
    try:
        backlog = manager.events_since(thread_id, since_seq)
        last_seq = since_seq or 0
        for record in backlog:
            last_seq = max(last_seq, record.seq)
            payload = runtime_event_payload(record)
            yield sse_frame(record.event, payload)

        goal_snapshot = _goal_status_snapshot(manager, thread_id)
        if goal_snapshot is not None:
            yield sse_frame("goal.status", goal_snapshot)

        while True:
            if is_disconnected is not None and await is_disconnected():
                return
            try:
                record = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if record.thread_id != thread_id:
                continue
            if record.seq <= last_seq:
                continue
            last_seq = record.seq
            payload = runtime_event_payload(record)
            yield sse_frame(record.event, payload)
    finally:
        manager.event_bus.unsubscribe(queue)


def _goal_status_snapshot(
    manager: RuntimeThreadManager, thread_id: str
) -> dict[str, Any] | None:
    """Build an out-of-band goal.status frame from the in-memory controller.

    Called once after backlog replay so the Workbench GoalChip is populated
    even when the last persisted goal.status event predates ``since_seq``.
    """
    state = manager._active.get(thread_id)
    if state is None:
        return None
    controller = getattr(state.engine, "goal_controller", None)
    if controller is None:
        return None
    goal = controller.current
    if goal is None:
        return None
    return {
        "seq": 0,
        "event": "goal.status",
        "payload": {
            "goal": {
                "goal_id": goal.goal_id,
                "objective": goal.objective[:120],
                "status": goal.status.value,
                "tokens_used": goal.usage.tokens_used,
                "token_budget": goal.token_budget,
                "active_seconds": round(goal.usage.active_seconds, 1),
            },
        },
    }
