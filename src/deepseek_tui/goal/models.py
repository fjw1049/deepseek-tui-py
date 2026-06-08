from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    BUDGET_LIMITED = "budget_limited"
    COMPLETE = "complete"


GoalEntryType = Literal["set", "usage", "clear"]


@dataclass(slots=True)
class GoalUsage:
    tokens_used: int = 0
    active_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "tokens_used": self.tokens_used,
            "active_seconds": self.active_seconds,
        }

    @classmethod
    def from_json(cls, raw: object) -> GoalUsage:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            tokens_used=max(0, int(raw.get("tokens_used") or 0)),
            active_seconds=max(0.0, float(raw.get("active_seconds") or 0.0)),
        )


@dataclass(slots=True)
class ThreadGoal:
    goal_id: str
    objective: str
    status: GoalStatus = GoalStatus.ACTIVE
    token_budget: int | None = None
    usage: GoalUsage = field(default_factory=GoalUsage)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "status": self.status.value,
            "token_budget": self.token_budget,
            "usage": self.usage.to_json(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "reason": self.reason,
        }

    @classmethod
    def from_json(cls, raw: object) -> ThreadGoal:
        if not isinstance(raw, dict):
            raise ValueError("goal must be an object")
        objective = str(raw.get("objective") or "").strip()
        if not objective:
            raise ValueError("goal objective is required")
        status_raw = str(raw.get("status") or GoalStatus.ACTIVE.value)
        try:
            status = GoalStatus(status_raw)
        except ValueError:
            status = GoalStatus.PAUSED
        budget = raw.get("token_budget")
        return cls(
            goal_id=str(raw.get("goal_id") or ""),
            objective=objective,
            status=status,
            token_budget=int(budget) if budget is not None else None,
            usage=GoalUsage.from_json(raw.get("usage")),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            completed_at=(
                str(raw.get("completed_at")) if raw.get("completed_at") else None
            ),
            reason=str(raw.get("reason")) if raw.get("reason") else None,
        )


@dataclass(slots=True)
class GoalEntry:
    type: GoalEntryType
    goal_id: str
    timestamp: str
    goal: ThreadGoal | None = None
    tokens: int = 0
    active_seconds: float = 0.0
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "goal_id": self.goal_id,
            "timestamp": self.timestamp,
        }
        if self.goal is not None:
            data["goal"] = self.goal.to_json()
        if self.tokens:
            data["tokens"] = self.tokens
        if self.active_seconds:
            data["active_seconds"] = self.active_seconds
        if self.reason:
            data["reason"] = self.reason
        return data

    @classmethod
    def from_json(cls, raw: object) -> GoalEntry:
        if not isinstance(raw, dict):
            raise ValueError("goal entry must be an object")
        entry_type = raw.get("type")
        if entry_type not in {"set", "usage", "clear"}:
            raise ValueError(f"unknown goal entry type: {entry_type!r}")
        goal = ThreadGoal.from_json(raw["goal"]) if isinstance(raw.get("goal"), dict) else None
        return cls(
            type=entry_type,
            goal_id=str(raw.get("goal_id") or (goal.goal_id if goal else "")),
            timestamp=str(raw.get("timestamp") or ""),
            goal=goal,
            tokens=max(0, int(raw.get("tokens") or 0)),
            active_seconds=max(0.0, float(raw.get("active_seconds") or 0.0)),
            reason=str(raw.get("reason")) if raw.get("reason") else None,
        )
