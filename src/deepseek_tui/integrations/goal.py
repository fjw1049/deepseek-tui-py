"""Goal tracking & multi-step task coordination.

Consolidates the former goal/ package into a single integration module.
"""

from __future__ import annotations



import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


# ======================================================================
# From models.py
# ======================================================================


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


# ======================================================================
# From state.py
# ======================================================================


from datetime import datetime, timezone
from uuid import uuid4


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


# ======================================================================
# From transition.py
# ======================================================================


from dataclasses import dataclass, field
from typing import Literal


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


# ======================================================================
# From accounting.py
# ======================================================================


from time import monotonic

from deepseek_tui.protocol.responses import Usage


def tokens_from_usage(usage: Usage | None) -> int:
    if usage is None:
        return 0
    return max(0, int(usage.input_tokens)) + max(0, int(usage.output_tokens))


class GoalAccounting:
    def __init__(self) -> None:
        self._turn_started_at: float | None = None

    def start_turn(self) -> None:
        self._turn_started_at = monotonic()

    def finish_turn(self) -> float:
        if self._turn_started_at is None:
            return 0.0
        elapsed = max(0.0, monotonic() - self._turn_started_at)
        self._turn_started_at = None
        return elapsed


# ======================================================================
# From prompts.py
# ======================================================================



CONTINUATION_MARKER = "<deepseek_goal_continuation"


def continuation_prompt(goal: ThreadGoal) -> str:
    return (
        f'{CONTINUATION_MARKER} goal_id="{goal.goal_id}">\n'
        "Continue working on the active goal below. First audit whether it is "
        "already genuinely complete. If it is complete, call update_goal with "
        'status="complete". Otherwise continue the next useful step.\n\n'
        "<goal_objective>\n"
        f"{goal.objective}\n"
        "</goal_objective>\n"
        "</deepseek_goal_continuation>"
    )


def budget_limited_message(goal: ThreadGoal) -> str:
    return (
        "The active goal has reached its token budget. Pause autonomous work "
        "and summarize the current state for the user."
    )


# ======================================================================
# From persistence.py
# ======================================================================


import json
import os
import shutil
from pathlib import Path


_GENERIC_SESSION_IDS = frozenset({"current", "latest", "default", ""})


def safe_thread_id(thread_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in thread_id)


def goal_journal_path(workspace: Path, thread_id: str) -> Path:
    return workspace.resolve() / ".deepseek" / "goals" / f"{safe_thread_id(thread_id)}.jsonl"


def resolve_goal_thread_id(
    metadata: dict,
    *,
    fallback_id: str,
    workspace: Path,
) -> str:
    """Pick the journal key for resume/rebind, including legacy session files."""
    goals_dir = workspace.resolve() / ".deepseek" / "goals"
    candidates: list[str] = []
    for key in ("id", "memory_thread_id"):
        val = metadata.get(key)
        if isinstance(val, str):
            text = val.strip()
            if text and text.lower() not in _GENERIC_SESSION_IDS:
                candidates.append(text)
    fallback = fallback_id.strip()
    if fallback and fallback.lower() not in _GENERIC_SESSION_IDS:
        candidates.append(fallback)

    for candidate in candidates:
        if goal_journal_path(workspace, candidate).exists():
            return candidate

    for key in ("id", "memory_thread_id"):
        val = metadata.get(key)
        if isinstance(val, str):
            text = val.strip()
            if text and text.lower() not in _GENERIC_SESSION_IDS:
                return text

    if goals_dir.is_dir():
        journals = [p for p in goals_dir.glob("*.jsonl") if p.stat().st_size > 0]
        if len(journals) == 1:
            return journals[0].stem

    if candidates:
        return candidates[0]
    return fallback or "default"


def copy_goal_journal_file(
    source: Path,
    target: Path,
    *,
    pause_reason: str = "paused after thread fork",
) -> None:
    """Copy a journal file and pause any active goal on the fork branch."""
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    journal = GoalJournal(target)
    goal = journal.load_goal()
    if goal is not None and goal.status == GoalStatus.ACTIVE:
        journal.append(
            set_entry(
                update_status(goal, GoalStatus.PAUSED, reason=pause_reason),
            )
        )


def copy_goal_journal_for_fork(
    workspace: Path,
    source_thread_id: str,
    target_thread_id: str,
    *,
    pause_reason: str = "paused after thread fork",
) -> None:
    """TUI/workspace fork helper under ``.deepseek/goals/``."""
    copy_goal_journal_file(
        goal_journal_path(workspace, source_thread_id),
        goal_journal_path(workspace, target_thread_id),
        pause_reason=pause_reason,
    )


class GoalJournal:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_workspace(cls, workspace: Path, thread_id: str) -> GoalJournal:
        return cls(goal_journal_path(workspace, thread_id))

    def read_entries(self) -> list[GoalEntry]:
        if not self.path.exists():
            return []
        entries: list[GoalEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(GoalEntry.from_json(json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
        return entries

    def load_goal(self) -> ThreadGoal | None:
        return reconstruct_goal(self.read_entries())

    def append(self, entry: GoalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry.to_json(), ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())


# ======================================================================
# From recovery.py
# ======================================================================


from dataclasses import dataclass
from enum import Enum


class FailureKind(Enum):
    USER_CANCEL = "user_cancel"
    FATAL = "fatal"
    CONTEXT_OVERFLOW = "context_overflow"
    TRANSIENT = "transient"


class FailureAction(Enum):
    PAUSE_NOW = "pause_now"
    COUNTED = "counted"
    OVERFLOW_WAIT = "overflow_wait"


_USER_CANCEL_REASONS = frozenset(
    {
        "user_cancelled",
        "interrupt_requested",
    }
)

_FATAL_MARKERS = (
    "quota",
    "rate_limit",
    "unauthorized",
    "authentication",
    "invalid_api_key",
    "permission_denied",
    "engine_error",
)


def classify_failure(reason: str) -> FailureKind:
    normalized = (reason or "").strip().lower()
    if normalized in _USER_CANCEL_REASONS:
        return FailureKind.USER_CANCEL
    if normalized == "context_overflow":
        return FailureKind.CONTEXT_OVERFLOW
    if any(marker in normalized for marker in _FATAL_MARKERS):
        return FailureKind.FATAL
    return FailureKind.TRANSIENT


@dataclass(slots=True)
class GoalRecovery:
    max_consecutive_failures: int = 3
    max_overflow_failures: int = 3
    consecutive_failures: int = 0
    overflow_failures: int = 0

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.overflow_failures = 0

    def evaluate_failure(self, reason: str) -> FailureAction:
        kind = classify_failure(reason)
        if kind in {FailureKind.USER_CANCEL, FailureKind.FATAL}:
            return FailureAction.PAUSE_NOW
        if kind == FailureKind.CONTEXT_OVERFLOW:
            self.overflow_failures += 1
            if self.overflow_failures >= self.max_overflow_failures:
                return FailureAction.PAUSE_NOW
            return FailureAction.OVERFLOW_WAIT
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_consecutive_failures:
            return FailureAction.PAUSE_NOW
        return FailureAction.COUNTED


# ======================================================================
# From stale_guard.py
# ======================================================================




def is_follow_up_stale(goal: ThreadGoal | None, goal_id: str) -> bool:
    return goal is None or goal.goal_id != goal_id or goal.status != GoalStatus.ACTIVE


# ======================================================================
# From continuation.py
# ======================================================================


from dataclasses import dataclass



@dataclass(slots=True)
class GoalFollowUp:
    goal_id: str
    content: str


def plan_follow_up(goal: ThreadGoal | None) -> GoalFollowUp | None:
    if goal is None or goal.status != GoalStatus.ACTIVE:
        return None
    return GoalFollowUp(goal_id=goal.goal_id, content=continuation_prompt(goal))


# ======================================================================
# From controller.py
# ======================================================================


from pathlib import Path
from typing import Any

from deepseek_tui.protocol.responses import Usage


class GoalController:
    def __init__(self, workspace: Path, thread_id: str) -> None:
        self.workspace = workspace.resolve()
        self.thread_id = thread_id or "default"
        self.journal = GoalJournal.for_workspace(self.workspace, self.thread_id)
        self.current: ThreadGoal | None = self.journal.load_goal()
        self.accounting = GoalAccounting()
        self.recovery = GoalRecovery()
        self._pending_follow_up: GoalFollowUp | None = None
        self._pending_steer: str | None = None
        self._on_change: Any | None = None

    def rebind(self, *, thread_id: str | None = None, journal_path: Path | None = None) -> None:
        if thread_id is not None:
            self.thread_id = thread_id or "default"
        if journal_path is not None:
            self.journal = GoalJournal(journal_path)
        else:
            self.journal = GoalJournal.for_workspace(self.workspace, self.thread_id)
        self.current = self.journal.load_goal()
        self._pending_follow_up = None
        self._pending_steer = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "goal": self.current.to_json() if self.current is not None else None,
            "pending_follow_up": (
                self._pending_follow_up.goal_id if self._pending_follow_up else None
            ),
        }

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def create(
        self, objective: str, token_budget: int | None = None, *, replace_existing: bool = False
    ) -> ThreadGoal:
        # If replacing, clear existing goal first
        if replace_existing and self.current is not None and self.current.status != GoalStatus.COMPLETE:
            self.journal.append(clear_entry(self.current, reason="replaced"))
            self.current = None

        result = plan_goal_transition(
            self.current,
            "create",
            objective=objective,
            token_budget=token_budget,
        )
        assert result.goal is not None
        self.current = result.goal
        self.journal.append(set_entry(self.current))
        # Queue immediate follow-up so agent starts working on the goal
        self._pending_follow_up = plan_follow_up(self.current)
        self._notify_change()
        return self.current

    def pause(self, reason: str | None = None) -> ThreadGoal | None:
        goal = self._apply_status("pause", reason=reason)
        self._pending_follow_up = None
        return goal

    def resume(self) -> ThreadGoal | None:
        goal = self._apply_status("resume")
        # Queue follow-up so agent resumes working
        self._pending_follow_up = plan_follow_up(goal)
        return goal

    def complete(self, reason: str | None = None) -> ThreadGoal | None:
        return self._apply_status("complete", reason=reason)

    def clear(self, reason: str | None = None) -> None:
        if self.current is None:
            return
        self.journal.append(clear_entry(self.current, reason=reason))
        self.current = None
        self._pending_follow_up = None
        self._notify_change()

    def _apply_status(self, request: str, *, reason: str | None = None) -> ThreadGoal | None:
        result = plan_goal_transition(self.current, request, reason=reason)  # type: ignore[arg-type]
        self.current = result.goal
        if result.persist == "set" and self.current is not None:
            self.journal.append(set_entry(self.current))
        elif result.persist == "clear" and self.current is not None:
            self.journal.append(clear_entry(self.current, reason=reason))
        if self.current is None or self.current.status != GoalStatus.ACTIVE:
            self._pending_follow_up = None
        self._notify_change()
        return self.current

    def on_turn_start(self) -> None:
        self.accounting.start_turn()

    def on_turn_complete(self, usage: Usage | None) -> GoalFollowUp | None:
        seconds = self.accounting.finish_turn()
        tokens = tokens_from_usage(usage)
        if self.current is not None and (tokens > 0 or seconds > 0):
            self.journal.append(usage_entry(self.current, tokens, seconds))
            self.current = apply_usage(self.current, tokens, seconds)
            if self.current.status == GoalStatus.BUDGET_LIMITED:
                self.journal.append(set_entry(self.current))
                # Queue budget steer message for the model
                self._pending_steer = budget_limited_message(self.current)
                self._pending_follow_up = None
                return None
        self.recovery.record_success()
        self._pending_follow_up = plan_follow_up(self.current)
        return self._pending_follow_up

    def on_turn_failed(self, reason: str, usage: Usage | None = None) -> None:
        seconds = self.accounting.finish_turn()
        tokens = tokens_from_usage(usage)
        if self.current is None:
            return
        if tokens > 0 or seconds > 0:
            self.journal.append(usage_entry(self.current, tokens, seconds))
            self.current = apply_usage(self.current, tokens, seconds)
            if self.current.status == GoalStatus.BUDGET_LIMITED:
                self.journal.append(set_entry(self.current))
                self._pending_follow_up = None
                return

        if classify_failure(reason) == FailureKind.USER_CANCEL:
            pause_reason = "user cancelled" if reason == "user_cancelled" else reason
            self._apply_status("pause", reason=pause_reason)
            return

        action = self.recovery.evaluate_failure(reason)
        if action == FailureAction.PAUSE_NOW:
            self._apply_status("fail_pause", reason=reason)
        else:
            self._pending_follow_up = None

    def take_pending_follow_up(self) -> GoalFollowUp | None:
        follow_up = self._pending_follow_up
        self._pending_follow_up = None
        if follow_up is None:
            return None
        if is_follow_up_stale(self.current, follow_up.goal_id):
            return None
        return follow_up

    def take_pending_steer(self) -> str | None:
        """Return and clear any pending steer message (e.g. budget limit notice)."""
        steer = self._pending_steer
        self._pending_steer = None
        return steer

    def validate_follow_up(self, goal_id: str) -> bool:
        return not is_follow_up_stale(self.current, goal_id)


# ======================================================================
# From tools.py
# ======================================================================


import json
from typing import Any

from deepseek_tui.tools.registry import ToolCapability, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext

GOAL_CONTROLLER_KEY = "goal_controller"


def goal_controller_from_context(context: ToolContext) -> GoalController:
    controller = context.metadata.get(GOAL_CONTROLLER_KEY)
    if not isinstance(controller, GoalController):
        raise RuntimeError("goal runtime is not attached")
    return controller


class GetGoalTool(ToolSpec):
    def name(self) -> str:
        return "get_goal"

    def description(self) -> str:
        return "Get the current thread goal, status, token budget, and usage."

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        snapshot = goal_controller_from_context(context).snapshot()
        return ToolResult(True, json.dumps(snapshot, ensure_ascii=False))


class CreateGoalTool(ToolSpec):
    def name(self) -> str:
        return "create_goal"

    def description(self) -> str:
        return (
            "Create a thread goal with an optional token budget. "
            "Fails if an active goal already exists unless replace_existing=true."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "token_budget": {"type": "integer", "minimum": 1000},
                "replace_existing": {"type": "boolean", "default": False},
            },
            "required": ["objective"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return []

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            budget = (
                int(input_data["token_budget"])
                if input_data.get("token_budget") is not None
                else None
            )
            replace = bool(input_data.get("replace_existing", False))
            goal = goal_controller_from_context(context).create(
                str(input_data.get("objective") or ""),
                budget,
                replace_existing=replace,
            )
        except ValueError as exc:
            return ToolResult(False, str(exc))
        return ToolResult(True, json.dumps(goal.to_json(), ensure_ascii=False))


class UpdateGoalTool(ToolSpec):
    def name(self) -> str:
        return "update_goal"

    def description(self) -> str:
        return "Mark the current goal complete after verifying the objective is genuinely done."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["complete"]},
                "reason": {"type": "string"},
            },
            "required": ["status"],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return []

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        if input_data.get("status") != "complete":
            return ToolResult(False, "model may only set goal status to complete")
        goal = goal_controller_from_context(context).complete(
            str(input_data.get("reason") or "verified complete")
        )
        if goal is None:
            return ToolResult(False, "no active goal")
        return ToolResult(True, json.dumps(goal.to_json(), ensure_ascii=False))


def goal_tools() -> list[ToolSpec]:
    return [GetGoalTool(), CreateGoalTool(), UpdateGoalTool()]
