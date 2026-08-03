"""Regression tests for the checklist turn-end gate.

The gate blocks ending a turn ONCE when the checklist still has open
(``pending``/``in_progress``) items, forcing the model to reconcile them.
It does not judge whether the work is done and never loops the model.

These tests exercise the isolable pieces: the ``_open_checklist_summary``
helper on the Engine (fed via the real ``checklist`` tool so the store shape
is authentic) and the reminder registration/format.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine import reminders
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.prompts import CHECKLIST_GATE_REMINDER
from deepseek_tui.tools.registry import ToolContext, build_default_registry


def _engine_with_context() -> tuple[Engine, ToolContext]:
    ctx = ToolContext(working_directory="/tmp")
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ctx)
    return engine, ctx


async def _write(ctx: ToolContext, todos: list[dict]) -> None:
    registry = build_default_registry(mode="agent")
    await registry.execute("checklist", {"todos": todos}, ctx)


@pytest.mark.asyncio
async def test_summary_empty_when_no_checklist() -> None:
    engine, _ = _engine_with_context()
    assert engine._open_checklist_summary() == ""


@pytest.mark.asyncio
async def test_summary_empty_when_all_resolved() -> None:
    engine, ctx = _engine_with_context()
    await _write(
        ctx,
        [
            {"content": "A", "status": "completed"},
            {"content": "B", "status": "cancelled"},
        ],
    )
    assert engine._open_checklist_summary() == ""


@pytest.mark.asyncio
async def test_summary_lists_open_items() -> None:
    engine, ctx = _engine_with_context()
    await _write(
        ctx,
        [
            {"content": "A", "status": "completed"},
            {"content": "B", "status": "in_progress"},
            {"content": "C", "status": "pending"},
        ],
    )
    summary = engine._open_checklist_summary()
    # Only the open items appear; the completed one does not.
    assert "#2 in_progress" in summary
    assert "#3 pending" in summary
    assert "#1" not in summary


def test_gate_reminder_registered_and_tail() -> None:
    spec = reminders.CHECKLIST_INCOMPLETE_GATE
    assert spec in reminders.REGISTRY
    assert spec.placement is reminders.Placement.TAIL
    # Priority sits between the drift re-anchor (20) and diagnostics (30).
    assert 20 < spec.priority < 30


def test_gate_reminder_formats() -> None:
    body = CHECKLIST_GATE_REMINDER.format(open_summary="#2 in_progress")
    assert "#2 in_progress" in body
    assert 'op="update"' in body
    # Renders inside the ALERT envelope without error.
    rendered = reminders.render(reminders.CHECKLIST_INCOMPLETE_GATE, body)
    assert rendered.startswith("<system-reminder>")


@pytest.mark.asyncio
async def test_reconcile_cancels_open_items_only() -> None:
    from deepseek_tui.tools.todo import reconcile_open_checklist_items

    engine, ctx = _engine_with_context()
    await _write(
        ctx,
        [
            {"content": "A", "status": "completed"},
            {"content": "B", "status": "in_progress"},
            {"content": "C", "status": "pending"},
            {"content": "D", "status": "cancelled"},
        ],
    )
    reconciled = reconcile_open_checklist_items(ctx)
    assert reconciled is not None
    content, metadata = reconciled
    assert "turn end" in content
    items = metadata["items"]
    by_content = {row["content"]: row["status"] for row in items}
    assert by_content == {
        "A": "completed",
        "B": "cancelled",
        "C": "cancelled",
        "D": "cancelled",
    }
    assert engine._open_checklist_summary() == ""
    # Second call is a no-op once everything is closed.
    assert reconcile_open_checklist_items(ctx) is None
