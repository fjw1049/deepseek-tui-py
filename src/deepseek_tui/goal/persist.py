"""Serialize / restore GoalService state."""

from __future__ import annotations

from copy import deepcopy

from typing import Any

from deepseek_tui.goal.queue import GoalQueue, item_from_dict
from deepseek_tui.goal.state import GoalState, restore_pause
from deepseek_tui.goal.types import (
    GoalBudgetLimits,
    MAX_UNRESOLVED_FAILURES,
    GoalDump,
    GoalStatus,
)


def state_to_dict(state: GoalState) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "evidence_overflow": state.evidence_overflow,
        "queue_item_id": state.queue_item_id,
        "goal_id": state.goal_id,
        "objective": state.objective,
        "completion_criterion": state.completion_criterion,
        "status": state.status.value,
        "turns_used": state.turns_used,
        "tokens_used": state.tokens_used,
        "wall_clock_ms": state.settle_clock().wall_clock_ms,
        "terminal_reason": state.terminal_reason,
        "checklist": [dict(item) for item in state.checklist],
        "evidence": [dict(item) for item in state.evidence],
        "completion_evidence": list(state.completion_evidence),
        "work_revision": state.work_revision,
        "last_progress_signature": state.last_progress_signature,
        "stalled_turns": state.stalled_turns,
        "requirements": [dict(item) for item in state.requirements],
        "completion_audit": deepcopy(state.completion_audit),
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
    if status is GoalStatus.BLOCKED and str(data.get("terminal_reason", "")).startswith(
        "Blocked after goal budget reached:"
    ):
        status = GoalStatus.BUDGET_LIMITED
    goal_id = data.get("goal_id")
    state = GoalState(
        goal_id=str(goal_id) if goal_id else "restored",
        evidence_overflow=data.get("evidence_overflow") is True,
        queue_item_id=data.get("queue_item_id") if isinstance(data.get("queue_item_id"), str) else None,
        objective=objective.strip(),
        completion_criterion=(
            str(data["completion_criterion"]).strip()
            if isinstance(data.get("completion_criterion"), str)
            and str(data["completion_criterion"]).strip()
            else None
        ),
        status=status,
        turns_used=_opt_int(data.get("turns_used")) or 0,
        tokens_used=_opt_int(data.get("tokens_used")) or 0,
        wall_clock_ms=_opt_int(data.get("wall_clock_ms")) or 0,
        budget_limits=limits,
        terminal_reason=(
            str(data["terminal_reason"]) if isinstance(data.get("terminal_reason"), str) else None
        ),
        checklist=[
            {
                **item,
                "status": item["status"]
                if item["status"] in {"pending", "in_progress", "completed", "cancelled"}
                else "pending",
            }
            for item in _list(data.get("checklist"))
            if isinstance(item, dict)
            and all(isinstance(item.get(k), str) for k in ("id", "content", "status"))
        ],
        evidence=[dict(item) for item in _list(data.get("evidence")) if _valid_evidence(item)],
        completion_evidence=tuple(
            item for item in _list(data.get("completion_evidence")) if isinstance(item, str)
        ),
        work_revision=_opt_int(data.get("work_revision")) or 0,
    )
    if len(state.evidence) > MAX_UNRESOLVED_FAILURES + 80:
        state.evidence = state.evidence[-(MAX_UNRESOLVED_FAILURES + 80):]
        state.evidence_overflow = True
    state.requirements = [{"id": "objective", "content": state.objective}]
    if state.completion_criterion:
        state.requirements.append({"id": "criterion", "content": state.completion_criterion})
    known = {item["id"] for item in state.requirements}
    for item in _list(data.get("requirements")):
        if (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"] not in known
            and isinstance(item.get("content"), str)
            and item["content"].strip()
        ):
            state.requirements.append({"id": item["id"], "content": item["content"]})
            known.add(item["id"])
    state.completion_audit = (
        deepcopy(data["completion_audit"]) if isinstance(data.get("completion_audit"), dict) else {}
    )
    if state.status is not GoalStatus.COMPLETE:
        # Files may have changed while the process was down; keep the history,
        # but require fresh verification after restoring an unfinished goal.
        state.work_revision += 1
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
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _valid_evidence(item: object) -> bool:
    return (
        isinstance(item, dict)
        and all(isinstance(item.get(k), str) for k in ("tool_call_id", "signature", "tool"))
        and all(isinstance(item.get(k), bool) for k in ("success", "finished", "verification"))
        and type(item.get("revision")) is int
    )
