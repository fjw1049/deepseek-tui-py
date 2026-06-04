"""Workflow progress item finalization tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from deepseek_tui.app_server.broadcast import AsyncBroadcast
from deepseek_tui.app_server.runtime_threads import (
    EVENT_CHANNEL_CAPACITY,
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
)
from deepseek_tui.app_server.thread_manager import RuntimeThreadManager


@pytest.mark.asyncio
async def test_interrupted_turn_finalizes_orphan_workflow_progress_item(
    tmp_path,
) -> None:
    store = RuntimeThreadStore(tmp_path)
    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager.store = store
    manager.event_bus = AsyncBroadcast(capacity=EVENT_CHANNEL_CAPACITY)

    now = datetime.now(timezone.utc)
    item = TurnItemRecord(
        id="item_workflow",
        turn_id="turn_1",
        kind=TurnItemKind.STATUS,
        status=TurnItemLifecycleStatus.IN_PROGRESS,
        summary="workflow:demo",
        detail=json.dumps(
            {
                "tool_call_id": "tc_workflow",
                "workflow_name": "demo",
                "snapshot": {
                    "name": "demo",
                    "description": "d",
                    "phases": [],
                    "logs": [],
                    "agents": [],
                    "agent_count": 0,
                    "running_count": 1,
                    "done_count": 0,
                    "error_count": 0,
                },
                "completed": False,
                "status": "running",
            }
        ),
        metadata={"workflow_progress": True},
        started_at=now,
    )
    store.save_item(item)

    workflow_items = {"tc_workflow": "item_workflow"}
    await manager._finalize_orphan_workflow_items(
        "thread_1",
        "turn_1",
        workflow_items,
        RuntimeTurnStatus.INTERRUPTED,
    )

    saved = store.load_item("item_workflow")
    payload = json.loads(saved.detail or "{}")
    events = store.events_since("thread_1", 0)

    assert saved.status == TurnItemLifecycleStatus.INTERRUPTED
    assert payload["completed"] is True
    assert payload["status"] == "cancelled"
    assert workflow_items == {}
    assert [event.event for event in events] == [
        "item.interrupted",
        "workflow.progress",
    ]
    assert events[-1].payload["status"] == "cancelled"
