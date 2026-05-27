"""Approval input summaries for tool arguments."""

from __future__ import annotations

from deepseek_tui.engine.engine import _summarize_call_args


def test_checklist_update_shows_item_and_status() -> None:
    summary = _summarize_call_args({"item_id": "1", "status": "completed"})
    assert summary == "checklist item #1 → completed"


def test_checklist_update_includes_content_when_present() -> None:
    summary = _summarize_call_args(
        {
            "item_id": "3",
            "status": "in_progress",
            "content": "Write architecture report",
        }
    )
    assert "item #3" in summary
    assert "in_progress" in summary
    assert "Write architecture report" in summary


def test_checklist_write_lists_todo_preview() -> None:
    summary = _summarize_call_args(
        {
            "todos": [
                {"content": "Scan repo", "status": "completed"},
                {"content": "Write report", "status": "pending"},
            ]
        }
    )
    assert summary.startswith("checklist (2 items):")
    assert "Scan repo" in summary
    assert "Write report" in summary


def test_exec_shell_still_prefers_command() -> None:
    summary = _summarize_call_args({"command": "npm test", "cwd": "/tmp"})
    assert summary == "npm test"
