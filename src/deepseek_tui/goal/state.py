from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from deepseek_tui.goal.models import GoalEntry, GoalStatus, GoalUsage, ThreadGoal

MAX_OBJECTIVE_CHARS = 12_000
MIN_TOKEN_BUDGET = 1_000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_objective(objective: str) -> str:
    text = objective.strip()
    if not text:
        raise ValueError("objective is required")
    if len(text) > MAX_OBJECTIVE_CHARS:
        raise ValueError(f"objective is too long (max {MAX_OBJECTIVE_CHARS} chars)")
    return text


def validate_token_budget(token_budget: int | None) -> int | None:
    if token_budget is None:
        return None
    budget = int(token_budget)
    if budget < MIN_TOKEN_BUDGET:
        raise ValueError(f"token_budget must be at least {MIN_TOKEN_BUDGET}")
    return budget


def create_goal(objective: str, token_budget: int | None = None) -> ThreadGoal:
    timestamp = now_iso()
    return ThreadGoal(
        goal_id=f"goal_{uuid4().hex[:12]}",
        objective=validate_objective(objective),
        status=GoalStatus.ACTIVE,
        token_budget=validate_token_budget(token_budget),
        usage=GoalUsage(),
        created_at=timestamp,
        updated_at=timestamp,
    )


def apply_usage(goal: ThreadGoal, tokens: int, active_seconds: float) -> ThreadGoal:
    if tokens <= 0 and active_seconds <= 0:
        return goal
    updated = ThreadGoal.from_json(goal.to_json())
    updated.usage.tokens_used += max(0, int(tokens))
    updated.usage.active_seconds += max(0.0, float(active_seconds))
    updated.updated_at = now_iso()
    if (
        updated.status == GoalStatus.ACTIVE
        and updated.token_budget is not None
        and updated.usage.tokens_used >= updated.token_budget
    ):
        updated.status = GoalStatus.BUDGET_LIMITED
        updated.reason = "token budget reached"
    return updated


def update_status(
    goal: ThreadGoal,
    status: GoalStatus,
    *,
    reason: str | None = None,
) -> ThreadGoal:
    updated = ThreadGoal.from_json(goal.to_json())
    updated.status = status
    updated.reason = reason
    updated.updated_at = now_iso()
    updated.completed_at = now_iso() if status == GoalStatus.COMPLETE else None
    return updated


def reconstruct_goal(entries: list[GoalEntry]) -> ThreadGoal | None:
    current: ThreadGoal | None = None
    for entry in entries:
        if entry.type == "set":
            current = ThreadGoal.from_json(entry.goal.to_json()) if entry.goal else None
        elif entry.type == "usage" and current is not None:
            if entry.goal_id == current.goal_id:
                current = apply_usage(current, entry.tokens, entry.active_seconds)
        elif entry.type == "clear":
            if current is not None and entry.goal_id == current.goal_id:
                current = None
    return current


def set_entry(goal: ThreadGoal) -> GoalEntry:
    return GoalEntry(
        type="set",
        goal_id=goal.goal_id,
        goal=goal,
        timestamp=now_iso(),
    )


def usage_entry(goal: ThreadGoal, tokens: int, active_seconds: float) -> GoalEntry:
    return GoalEntry(
        type="usage",
        goal_id=goal.goal_id,
        tokens=max(0, int(tokens)),
        active_seconds=max(0.0, float(active_seconds)),
        timestamp=now_iso(),
    )


def clear_entry(goal: ThreadGoal, reason: str | None = None) -> GoalEntry:
    return GoalEntry(
        type="clear",
        goal_id=goal.goal_id,
        timestamp=now_iso(),
        reason=reason,
    )
