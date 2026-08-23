"""Regression tests for the checklist turn-end gate.

The gate blocks ending a turn while the checklist still has open
(``pending``/``in_progress``) items, forcing the model to face them. It
re-fires only while blocking produces progress, and releases as soon as a
block changes nothing — unfinished work keeps getting pushed without the
livelock a fire-until-empty gate would have. It never judges whether the
work is done.

A no-tool stop with visible text is held. Checklist-only tools that
clear the list keep that stop (tracking was stale). Any other tool
means the stop was premature and the loop continues.

These tests exercise the isolable pieces: the ``_open_checklist_summary`` and
``_next_checklist_gate_summary`` helpers on the Engine (fed via the real
``checklist`` tool so the store shape is authentic) and the reminder
registration/format.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine import reminders
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.orchestrator.core import _CHECKLIST_GATE_MAX_FIRES
from deepseek_tui.engine.prompts import CHECKLIST_GATE_REMINDER
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolContext, build_default_registry


def _engine_with_context() -> tuple[Engine, ToolContext]:
    ctx = ToolContext(working_directory="/tmp")
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ctx)
    return engine, ctx


async def _write(ctx: ToolContext, todos: list[dict]) -> None:
    registry = build_default_registry(mode="agent")
    await registry.execute("checklist", {"todos": todos}, ctx)


async def _update(ctx: ToolContext, item_id: str, status: str) -> None:
    registry = build_default_registry(mode="agent")
    await registry.execute(
        "checklist", {"op": "update", "id": item_id, "status": status}, ctx
    )


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


@pytest.mark.asyncio
async def test_gate_stays_quiet_when_nothing_is_open() -> None:
    engine, ctx = _engine_with_context()
    await _write(ctx, [{"content": "A", "status": "completed"}])
    assert engine._next_checklist_gate_summary(fired=0, last_open=None) is None


@pytest.mark.asyncio
async def test_gate_fires_on_the_first_stop_attempt() -> None:
    engine, ctx = _engine_with_context()
    await _write(ctx, [{"content": "A", "status": "pending"}])
    summary = engine._next_checklist_gate_summary(fired=0, last_open=None)
    assert summary is not None
    assert "#1 pending" in summary


@pytest.mark.asyncio
async def test_gate_releases_when_the_block_changed_nothing() -> None:
    """A model that will not reconcile costs one extra round, not a livelock."""
    engine, ctx = _engine_with_context()
    await _write(ctx, [{"content": "A", "status": "pending"}])
    first = engine._next_checklist_gate_summary(fired=0, last_open=None)
    assert first is not None
    # Nothing moved since the block — honor the stop.
    assert engine._next_checklist_gate_summary(fired=1, last_open=first) is None


@pytest.mark.asyncio
async def test_gate_refires_while_the_model_keeps_making_progress() -> None:
    engine, ctx = _engine_with_context()
    await _write(
        ctx,
        [
            {"content": "A", "status": "pending"},
            {"content": "B", "status": "pending"},
        ],
    )
    first = engine._next_checklist_gate_summary(fired=0, last_open=None)
    assert first is not None

    await _update(ctx, "1", "completed")
    second = engine._next_checklist_gate_summary(fired=1, last_open=first)
    assert second is not None
    assert second != first
    assert "#2 pending" in second
    assert "#1" not in second


def _checklist_update(item_id: str, status: str) -> ToolCall:
    return ToolCall(
        id=f"call_{item_id}",
        name="checklist",
        arguments={"op": "update", "id": item_id, "status": status},
    )


@pytest.mark.asyncio
async def test_held_stop_survives_when_tracking_clears_the_list() -> None:
    engine, ctx = _engine_with_context()
    await _write(ctx, [{"content": "A", "status": "in_progress"}])
    await _update(ctx, "1", "completed")
    assert engine._accept_held_stop_after_tools(
        held=True,
        tool_calls=[_checklist_update("1", "completed")],
        tool_errors=0,
    )


@pytest.mark.asyncio
async def test_held_stop_does_not_survive_when_items_remain_open() -> None:
    engine, ctx = _engine_with_context()
    await _write(
        ctx,
        [
            {"content": "A", "status": "in_progress"},
            {"content": "B", "status": "pending"},
        ],
    )
    assert not engine._accept_held_stop_after_tools(
        held=True,
        tool_calls=[_checklist_update("1", "in_progress")],
        tool_errors=0,
    )


@pytest.mark.asyncio
async def test_held_stop_does_not_survive_real_work() -> None:
    engine, ctx = _engine_with_context()
    await _write(ctx, [{"content": "A", "status": "pending"}])
    assert not engine._accept_held_stop_after_tools(
        held=True,
        tool_calls=[
            ToolCall(id="r1", name="read_file", arguments={"path": "src/a.py"}),
        ],
        tool_errors=0,
    )


def test_empty_or_mixed_batches_are_not_tracking_only() -> None:
    engine, _ = _engine_with_context()
    assert not engine._is_checklist_batch([])
    assert engine._is_checklist_batch([_checklist_update("1", "completed")])
    assert not engine._is_checklist_batch(
        [
            _checklist_update("1", "completed"),
            ToolCall(id="r1", name="read_file", arguments={"path": "src/a.py"}),
        ]
    )


@pytest.mark.asyncio
async def test_gate_stops_at_the_hard_cap_even_with_progress() -> None:
    """Backstop for a model that closes one item and opens another each block."""
    engine, ctx = _engine_with_context()
    await _write(ctx, [{"content": "A", "status": "pending"}])
    assert (
        engine._next_checklist_gate_summary(
            fired=_CHECKLIST_GATE_MAX_FIRES, last_open="stale summary"
        )
        is None
    )


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


def test_gate_reminder_does_not_offer_in_progress_as_a_resting_state() -> None:
    """Turn-end reconcile cancels whatever is still open.

    The reminder used to close with "keep the item in_progress rather than
    marking it done", so a model that honestly reported partial work had that
    honesty flipped to ``cancelled`` with no explanation attached. The two
    exits it offers must be the ones that survive the turn end: finish the
    work, or cancel it with a reason.
    """
    body = CHECKLIST_GATE_REMINDER.format(open_summary="#2 in_progress")
    assert "keep the item in_progress" not in body
    assert "keep working and finish it" in body
    assert "cancelled" in body
    # And it must be honest about what happens to anything left open.
    assert "closed as cancelled" in body


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
    # Attribution matters: an item closed here was abandoned, which is not the
    # same as one the agent cancelled on purpose.
    assert "by the harness" in content
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
