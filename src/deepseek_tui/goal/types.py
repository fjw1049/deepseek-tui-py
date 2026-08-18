"""Goal Mode public types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

MAX_GOAL_OBJECTIVE_LENGTH = 4000
MAX_GOAL_COMPLETION_CRITERION_LENGTH = MAX_GOAL_OBJECTIVE_LENGTH
GOAL_SERVICE_KEY = "goal_service"
GOAL_TURN_ID_KEY = "goal_turn_id"
GOAL_CONTINUATION_KIND = "goal_continuation"
RESUME_AFTER_RESTORE_REASON = "Paused after agent resume"
STALE_GOAL_TOOL_MESSAGE = (
    "Goal changed since this turn started; ignored stale goal tool call."
)

CREATE_GOAL_NAME = "CreateGoal"
GET_GOAL_NAME = "GetGoal"
UPDATE_GOAL_NAME = "UpdateGoal"
SET_GOAL_BUDGET_NAME = "SetGoalBudget"

GOAL_TOOL_NAMES = frozenset(
    {CREATE_GOAL_NAME, GET_GOAL_NAME, UPDATE_GOAL_NAME, SET_GOAL_BUDGET_NAME}
)
GOAL_CONTROL_TOOL_NAMES = frozenset({UPDATE_GOAL_NAME, SET_GOAL_BUDGET_NAME})

ALLOWED_GOAL_MODES = frozenset({"agent", "yolo"})


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETE = "complete"


class GoalActor(str, Enum):
    USER = "user"
    MODEL = "model"
    RUNTIME = "runtime"
    SYSTEM = "system"


class GoalChangeKind(str, Enum):
    LIFECYCLE = "lifecycle"
    PROGRESS = "progress"
    COMPLETION = "completion"
    CLEARED = "cleared"


class GoalError(Exception):
    """User-facing goal command/tool failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class GoalBudgetLimits:
    token_budget: int | None = None
    turn_budget: int | None = None
    wall_clock_budget_ms: int | None = None

    def merged(self, other: GoalBudgetLimits) -> GoalBudgetLimits:
        return GoalBudgetLimits(
            token_budget=other.token_budget
            if other.token_budget is not None
            else self.token_budget,
            turn_budget=other.turn_budget
            if other.turn_budget is not None
            else self.turn_budget,
            wall_clock_budget_ms=other.wall_clock_budget_ms
            if other.wall_clock_budget_ms is not None
            else self.wall_clock_budget_ms,
        )


@dataclass(frozen=True, slots=True)
class GoalBudgetReport:
    token_budget: int | None
    turn_budget: int | None
    wall_clock_budget_ms: int | None
    remaining_tokens: int | None
    remaining_turns: int | None
    remaining_wall_clock_ms: int | None
    token_budget_reached: bool
    turn_budget_reached: bool
    wall_clock_budget_reached: bool
    over_budget: bool

    def nearing(self, used_tokens: int, used_turns: int, used_ms: int) -> bool:
        fractions: list[float] = []
        if self.turn_budget and self.turn_budget > 0:
            fractions.append(used_turns / self.turn_budget)
        if self.token_budget and self.token_budget > 0:
            fractions.append(used_tokens / self.token_budget)
        if self.wall_clock_budget_ms and self.wall_clock_budget_ms > 0:
            fractions.append(used_ms / self.wall_clock_budget_ms)
        return bool(fractions) and max(fractions) >= 0.75


@dataclass(frozen=True, slots=True)
class GoalSnapshot:
    goal_id: str
    objective: str
    completion_criterion: str | None
    status: GoalStatus
    turns_used: int
    tokens_used: int
    wall_clock_ms: int
    budget: GoalBudgetReport
    terminal_reason: str | None = None

    def for_model(self) -> dict[str, Any]:
        """Snapshot the model may see — never includes goal_id."""
        payload: dict[str, Any] = {
            "objective": self.objective,
            "status": self.status.value,
            "turns_used": self.turns_used,
            "tokens_used": self.tokens_used,
            "wall_clock_ms": self.wall_clock_ms,
            "budget": {
                "token_budget": self.budget.token_budget,
                "turn_budget": self.budget.turn_budget,
                "wall_clock_budget_ms": self.budget.wall_clock_budget_ms,
                "remaining_tokens": self.budget.remaining_tokens,
                "remaining_turns": self.budget.remaining_turns,
                "remaining_wall_clock_ms": self.budget.remaining_wall_clock_ms,
                "over_budget": self.budget.over_budget,
            },
        }
        if self.completion_criterion:
            payload["completion_criterion"] = self.completion_criterion
        if self.terminal_reason:
            payload["terminal_reason"] = self.terminal_reason
        return payload

    def to_dict(self) -> dict[str, Any]:
        data = {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "completion_criterion": self.completion_criterion,
            "status": self.status.value,
            "turns_used": self.turns_used,
            "tokens_used": self.tokens_used,
            "wall_clock_ms": self.wall_clock_ms,
            "terminal_reason": self.terminal_reason,
            "budget_limits": {
                "token_budget": self.budget.token_budget,
                "turn_budget": self.budget.turn_budget,
                "wall_clock_budget_ms": self.budget.wall_clock_budget_ms,
            },
        }
        return data


@dataclass(frozen=True, slots=True)
class GoalQueueItem:
    item_id: str
    objective: str

    def to_dict(self) -> dict[str, str]:
        return {"item_id": self.item_id, "objective": self.objective}


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    should_continue: bool
    prompt: str = ""
    reason: str = ""
    promote: GoalQueueItem | None = None


@dataclass(frozen=True, slots=True)
class GoalChange:
    kind: GoalChangeKind
    status: GoalStatus | None = None
    reason: str | None = None
    actor: GoalActor = GoalActor.USER


@dataclass(frozen=True, slots=True)
class GoalDump:
    goal: dict[str, Any] | None = None
    queue: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "queue": list(self.queue)}
