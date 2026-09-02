"""Pure GoalState mutations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace

from deepseek_tui.goal.types import (
    MAX_GOAL_COMPLETION_CRITERION_LENGTH,
    MAX_GOAL_OBJECTIVE_LENGTH,
    RESUME_AFTER_RESTORE_REASON,
    GoalBudgetLimits,
    GoalBudgetReport,
    GoalError,
    GoalSnapshot,
    GoalStatus,
)


@dataclass(slots=True)
class GoalState:
    goal_id: str
    objective: str
    completion_criterion: str | None
    status: GoalStatus
    turns_used: int
    tokens_used: int
    wall_clock_ms: int
    budget_limits: GoalBudgetLimits
    terminal_reason: str | None = None
    live_started_mono: float | None = None

    def live_wall_clock_ms(self, now_mono: float | None = None) -> int:
        extra = 0
        if self.status is GoalStatus.ACTIVE and self.live_started_mono is not None:
            clock = time.monotonic() if now_mono is None else now_mono
            extra = max(0, int((clock - self.live_started_mono) * 1000))
        return self.wall_clock_ms + extra

    def settle_clock(self, now_mono: float | None = None) -> GoalState:
        if self.status is not GoalStatus.ACTIVE or self.live_started_mono is None:
            return replace(self, live_started_mono=None)
        return replace(
            self,
            wall_clock_ms=self.live_wall_clock_ms(now_mono),
            live_started_mono=None,
        )

    def snapshot(self) -> GoalSnapshot:
        wall = self.live_wall_clock_ms()
        return GoalSnapshot(
            goal_id=self.goal_id,
            objective=self.objective,
            completion_criterion=self.completion_criterion,
            status=self.status,
            turns_used=self.turns_used,
            tokens_used=self.tokens_used,
            wall_clock_ms=wall,
            budget=compute_budget_report(
                self.budget_limits,
                self.tokens_used,
                self.turns_used,
                wall,
            ),
            terminal_reason=self.terminal_reason,
        )


def validate_objective(value: str) -> str:
    objective = value.strip()
    if not objective:
        raise GoalError("objective_empty", "Goal objective cannot be empty")
    if len(objective) > MAX_GOAL_OBJECTIVE_LENGTH:
        raise GoalError(
            "objective_too_long",
            f"Goal objective cannot exceed {MAX_GOAL_OBJECTIVE_LENGTH} characters",
        )
    return objective


def normalize_completion_criterion(value: str | None) -> str | None:
    trimmed = (value or "").strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_GOAL_COMPLETION_CRITERION_LENGTH:
        return trimmed[:MAX_GOAL_COMPLETION_CRITERION_LENGTH]
    return trimmed


def new_goal(
    objective: str,
    *,
    completion_criterion: str | None = None,
) -> GoalState:
    return GoalState(
        goal_id=str(uuid.uuid4()),
        objective=validate_objective(objective),
        completion_criterion=normalize_completion_criterion(completion_criterion),
        status=GoalStatus.ACTIVE,
        turns_used=0,
        tokens_used=0,
        wall_clock_ms=0,
        budget_limits=GoalBudgetLimits(),
        live_started_mono=time.monotonic(),
    )


def apply_status(
    state: GoalState,
    status: GoalStatus,
    *,
    reason: str | None = None,
) -> GoalState:
    settled = state.settle_clock()
    if status is GoalStatus.ACTIVE:
        return replace(
            settled,
            status=GoalStatus.ACTIVE,
            terminal_reason=None,
            live_started_mono=time.monotonic(),
        )
    return replace(
        settled,
        status=status,
        terminal_reason=reason,
        live_started_mono=None,
    )


def restore_pause(state: GoalState) -> GoalState:
    if state.status is not GoalStatus.ACTIVE:
        return replace(state, live_started_mono=None)
    return apply_status(state, GoalStatus.PAUSED, reason=RESUME_AFTER_RESTORE_REASON)


def compute_budget_report(
    limits: GoalBudgetLimits,
    tokens_used: int,
    turns_used: int,
    wall_clock_ms: int,
) -> GoalBudgetReport:
    token_budget = limits.token_budget
    turn_budget = limits.turn_budget
    wall_budget = limits.wall_clock_budget_ms
    token_reached = token_budget is not None and tokens_used >= token_budget
    turn_reached = turn_budget is not None and turns_used >= turn_budget
    wall_reached = wall_budget is not None and wall_clock_ms >= wall_budget
    return GoalBudgetReport(
        token_budget=token_budget,
        turn_budget=turn_budget,
        wall_clock_budget_ms=wall_budget,
        remaining_tokens=None if token_budget is None else max(0, token_budget - tokens_used),
        remaining_turns=None if turn_budget is None else max(0, turn_budget - turns_used),
        remaining_wall_clock_ms=(
            None if wall_budget is None else max(0, wall_budget - wall_clock_ms)
        ),
        token_budget_reached=token_reached,
        turn_budget_reached=turn_reached,
        wall_clock_budget_reached=wall_reached,
        over_budget=token_reached or turn_reached or wall_reached,
    )


def budget_block_reason(report: GoalBudgetReport) -> str | None:
    reached: list[str] = []
    if report.turn_budget_reached:
        reached.append(f"turn budget {report.turn_budget}")
    if report.token_budget_reached:
        reached.append(f"token budget {report.token_budget}")
    if report.wall_clock_budget_reached:
        reached.append(f"wall-clock budget {report.wall_clock_budget_ms}ms")
    if not reached:
        return None
    return "Blocked after goal budget reached: " + ", ".join(reached)
