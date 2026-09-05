"""UpdateGoal wrap-up text and stale-goal guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.tools import CreateGoalTool, SetGoalBudgetTool, UpdateGoalTool
from deepseek_tui.goal.types import (
    GOAL_SERVICE_KEY,
    GOAL_TURN_ID_KEY,
    STALE_GOAL_TOOL_MESSAGE,
    GoalStatus,
)
from deepseek_tui.tools.registry import ToolContext


def _context(service: GoalService, *, turn_id: str | None = None) -> ToolContext:
    metadata: dict[str, object] = {GOAL_SERVICE_KEY: service, "engine_mode": "agent"}
    if turn_id is not None:
        metadata[GOAL_TURN_ID_KEY] = turn_id
    return ToolContext(working_directory=Path("."), metadata=metadata)


@pytest.mark.asyncio
async def test_update_goal_complete_returns_wrap_up() -> None:
    service = GoalService()
    snapshot = service.create("Ship it")
    result = await UpdateGoalTool().execute(
        {"status": "complete", "reason": "done"},
        _context(service, turn_id=snapshot.goal_id),
    )
    assert result.success
    assert "Goal completed successfully: done" in result.content
    assert "Do not call more goal tools" in result.content
    assert service.snapshot() is None


@pytest.mark.asyncio
async def test_update_goal_blocked_returns_wrap_up() -> None:
    service = GoalService()
    snapshot = service.create("Ship it")
    result = await UpdateGoalTool().execute(
        {"status": "blocked", "reason": "need credentials"},
        _context(service, turn_id=snapshot.goal_id),
    )
    assert result.success
    assert result.content.startswith("Goal blocked.")
    assert service.snapshot() is not None
    assert service.snapshot().status is GoalStatus.BLOCKED


@pytest.mark.asyncio
async def test_update_goal_rejects_paused_status() -> None:
    service = GoalService()
    snapshot = service.create("Ship it")
    result = await UpdateGoalTool().execute(
        {"status": "paused"},
        _context(service, turn_id=snapshot.goal_id),
    )
    assert not result.success
    assert "Unknown goal status" in result.content
    assert service.snapshot() is not None
    assert service.snapshot().status is GoalStatus.ACTIVE


@pytest.mark.asyncio
async def test_control_tools_fail_cleanly_without_a_goal() -> None:
    service = GoalService()

    update = await UpdateGoalTool().execute(
        {"status": "complete"},
        _context(service),
    )
    budget = await SetGoalBudgetTool().execute(
        {"turnBudget": 3},
        _context(service),
    )

    assert not update.success
    assert not budget.success
    assert update.content == "No active goal"
    assert budget.content == "No current goal"


@pytest.mark.asyncio
async def test_stale_update_goal_is_ignored() -> None:
    service = GoalService()
    first = service.create("old")
    service.cancel()
    service.create("new")
    result = await UpdateGoalTool().execute(
        {"status": "complete"},
        _context(service, turn_id=first.goal_id),
    )
    assert not result.success
    assert result.content == STALE_GOAL_TOOL_MESSAGE
    assert service.snapshot() is not None
    assert service.snapshot().objective == "new"


@pytest.mark.asyncio
async def test_stale_set_budget_is_ignored() -> None:
    service = GoalService()
    first = service.create("old")
    service.cancel()
    result = await SetGoalBudgetTool().execute(
        {"turnBudget": 3},
        _context(service, turn_id=first.goal_id),
    )
    assert not result.success
    assert result.content == STALE_GOAL_TOOL_MESSAGE


@pytest.mark.asyncio
async def test_create_goal_adopts_live_turn() -> None:
    service = GoalService()
    service.on_turn_started()
    result = await CreateGoalTool().execute(
        {"objective": "Ship it"},
        _context(service),
    )
    assert result.success
    snap = service.snapshot()
    assert snap is not None
    assert snap.turns_used == 1
