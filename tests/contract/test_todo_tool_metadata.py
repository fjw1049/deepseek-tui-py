"""Checklist metadata merge for Workbench todo sidebar."""

from __future__ import annotations

from deepseek_tui.server.threads import todo_tool_metadata_from_result


def test_todo_metadata_prefers_task_updates_snapshot() -> None:
    result_meta = {
        "task_updates": {
            "checklist": {
                "items": [
                    {"id": 1, "content": "Scan repo", "status": "completed"},
                    {"id": 2, "content": "Write report", "status": "in_progress"},
                ],
                "completion_pct": 50,
                "in_progress_id": 2,
            }
        }
    }
    merged = todo_tool_metadata_from_result(
        "checklist_update",
        {"item_id": "2", "status": "in_progress"},
        result_meta,
        {"tool_name": "checklist_update"},
    )
    assert merged is not None
    assert len(merged["items"]) == 2
    assert merged["items"][0]["status"] == "completed"
    assert merged["items"][1]["status"] == "in_progress"
    assert merged["completion_pct"] == 50


def test_todo_metadata_merges_update_status_into_existing_items() -> None:
    existing = {
        "tool_name": "checklist_write",
        "items": [
            {"id": "1", "content": "A", "status": "completed"},
            {"id": "2", "content": "B", "status": "pending"},
        ],
        "completion_pct": 50,
    }
    merged = todo_tool_metadata_from_result(
        "checklist_update",
        {"item_id": "2", "status": "completed"},
        None,
        existing,
    )
    assert merged is not None
    assert merged["items"][1]["status"] == "completed"
    assert merged["completion_pct"] == 100
