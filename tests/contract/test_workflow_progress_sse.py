"""Contract: workflow.progress SSE envelope shape."""

from __future__ import annotations

from deepseek_tui.app_server.engine_bridge import engine_event_to_sse
from deepseek_tui.engine.events import WorkflowProgressEvent
from deepseek_tui.workflow.models import WorkflowSnapshot


def test_workflow_progress_sse_payload() -> None:
    snap = WorkflowSnapshot(name="demo", description="d", done_count=1, agent_count=2)
    ev = WorkflowProgressEvent(
        tool_call_id="tc_1",
        thread_id="thread_1",
        workflow_name="demo",
        snapshot=snap,
        completed=False,
        status="running",
    )
    frame = engine_event_to_sse(ev)
    assert frame["event"] == "workflow.progress"
    assert frame["tool_call_id"] == "tc_1"
    assert frame["workflow_name"] == "demo"
    assert frame["completed"] is False
    assert frame["status"] == "running"
    assert frame["snapshot"]["name"] == "demo"
    assert frame["snapshot"]["agent_count"] == 2
