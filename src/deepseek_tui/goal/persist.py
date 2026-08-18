"""Serialize / restore GoalService state."""

from __future__ import annotations

from typing import Any

from deepseek_tui.goal.queue import GoalQueue, item_from_dict
from deepseek_tui.goal.state import GoalState, restore_pause
from deepseek_tui.goal.types import (
    GoalBudgetLimits,
    GoalDump,
    GoalStatus,
)


def state_to_dict(state: GoalState) -> dict[str, Any]:
    return {
        "goal_id": state.goal_id,
        "objective": state.objective,
        "completion_criterion": state.completion_criterion,
        "status": state.status.value,
        "turns_used": state.turns_used,
        "tokens_used": state.tokens_used,
        "wall_clock_ms": state.settle_clock().wall_clock_ms,
        "terminal_reason": state.terminal_reason,
        "budget_limits": {
            "token_budget": state.budget_limits.token_budget,
            "turn_budget": state.budget_limits.turn_budget,
            "wall_clock_budget_ms": state.budget_limits.wall_clock_budget_ms,
        },
    }


def state_from_dict(data: dict[str, Any] | None) -> GoalState | None:
    if not isinstance(data, dict):
        return None
    objective = data.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        return None
    limits_raw = data.get("budget_limits")
    limits = GoalBudgetLimits()
    if isinstance(limits_raw, dict):
        limits = GoalBudgetLimits(
            token_budget=_opt_int(limits_raw.get("token_budget")),
            turn_budget=_opt_int(limits_raw.get("turn_budget")),
            wall_clock_budget_ms=_opt_int(limits_raw.get("wall_clock_budget_ms")),
        )
    try:
        status = GoalStatus(str(data.get("status") or "paused"))
    except ValueError:
        status = GoalStatus.PAUSED
    if status is GoalStatus.COMPLETE:
        return None
    goal_id = data.get("goal_id")
    state = GoalState(
        goal_id=str(goal_id) if goal_id else "restored",
        objective=objective.strip(),
        completion_criterion=(
            str(data["completion_criterion"]).strip()
            if isinstance(data.get("completion_criterion"), str)
            and str(data["completion_criterion"]).strip()
            else None
        ),
        status=status,
        turns_used=max(0, int(data.get("turns_used") or 0)),
        tokens_used=max(0, int(data.get("tokens_used") or 0)),
        wall_clock_ms=max(0, int(data.get("wall_clock_ms") or 0)),
        budget_limits=limits,
        terminal_reason=(
            str(data["terminal_reason"])
            if isinstance(data.get("terminal_reason"), str)
            else None
        ),
    )
    return restore_pause(state)


def dump_goal(state: GoalState | None, queue: GoalQueue) -> GoalDump:
    return GoalDump(
        goal=None if state is None else state_to_dict(state),
        queue=queue.to_list(),
    )


def load_queue(raw: object) -> GoalQueue:
    queue = GoalQueue()
    if not isinstance(raw, list):
        return queue
    for item in raw:
        parsed = item_from_dict(item) if isinstance(item, dict) else None
        if parsed is not None:
            queue.items.append(parsed)
    return queue


def apply_goal_to_engine(engine: Any, metadata: dict[str, Any] | None) -> None:
    """Restore a persisted goal onto an Engine (active → paused)."""
    service = getattr(engine, "goal_service", None)
    if service is None or not isinstance(metadata, dict):
        return
    service.restore(metadata.get("goal"), metadata.get("goal_queue"))


def _opt_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
