from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from deepseek_tui.goal.models import GoalStatus, ThreadGoal
from deepseek_tui.goal.state import create_goal, update_status

GoalRequest = Literal[
    "create",
    "pause",
    "resume",
    "complete",
    "clear",
    "fail_pause",
]


@dataclass(frozen=True, slots=True)
class GoalEffect:
    kind: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class GoalTransitionResult:
    goal: ThreadGoal | None
    persist: Literal["set", "clear", "skip"]
    effects: list[GoalEffect] = field(default_factory=list)


def plan_goal_transition(
    current: ThreadGoal | None,
    request: GoalRequest,
    *,
    objective: str | None = None,
    token_budget: int | None = None,
    reason: str | None = None,
) -> GoalTransitionResult:
    if request == "create":
        if objective is None:
            raise ValueError("objective is required")
        # Reject if there's already a non-complete goal (must clear/complete first)
        if current is not None and current.status != GoalStatus.COMPLETE:
            raise ValueError(
                f"an active goal already exists (status={current.status.value}). "
                "Complete or clear it first, or use replace_existing=true."
            )
        goal = create_goal(objective, token_budget)
        return GoalTransitionResult(
            goal=goal,
            persist="set",
            effects=[GoalEffect("goal_created", goal.objective)],
        )

    if current is None:
        return GoalTransitionResult(
            goal=None,
            persist="skip",
            effects=[GoalEffect("no_goal", "No active goal")],
        )

    if request == "pause":
        if current.status == GoalStatus.PAUSED:
            return GoalTransitionResult(current, "skip")
        return GoalTransitionResult(
            update_status(current, GoalStatus.PAUSED, reason=reason or "paused"),
            "set",
            [GoalEffect("goal_paused", reason or "paused")],
        )

    if request == "resume":
        if current.status == GoalStatus.COMPLETE:
            raise ValueError("completed goals cannot be resumed")
        if current.status == GoalStatus.BUDGET_LIMITED:
            raise ValueError(
                "budget-limited goals cannot be resumed without increasing the budget"
            )
        return GoalTransitionResult(
            update_status(current, GoalStatus.ACTIVE, reason=None),
            "set",
            [GoalEffect("goal_resumed")],
        )

    if request == "complete":
        return GoalTransitionResult(
            update_status(current, GoalStatus.COMPLETE, reason=reason or "complete"),
            "set",
            [GoalEffect("goal_completed")],
        )

    if request == "fail_pause":
        return GoalTransitionResult(
            update_status(current, GoalStatus.PAUSED, reason=reason or "turn failed"),
            "set",
            [GoalEffect("goal_paused_for_attention", reason or "turn failed")],
        )

    if request == "clear":
        return GoalTransitionResult(
            None,
            "clear",
            [GoalEffect("goal_cleared", reason or "cleared")],
        )

    raise ValueError(f"unknown goal request: {request}")
