"""Goal lifecycle, budget hard-stop, and continuation decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from deepseek_tui.goal.injection import GOAL_CONTINUATION_PROMPT, reminder_body
from deepseek_tui.goal.persist import dump_goal, load_queue, state_from_dict
from deepseek_tui.goal.queue import GoalQueue
from deepseek_tui.goal.state import (
    GoalState,
    apply_status,
    budget_block_reason,
    compute_budget_report,
    new_goal,
)
from deepseek_tui.goal.types import (
    ALLOWED_GOAL_MODES,
    ContinuationDecision,
    GoalActor,
    GoalBudgetLimits,
    GoalChange,
    GoalChangeKind,
    GoalDump,
    GoalError,
    GoalQueueItem,
    GoalSnapshot,
    GoalStatus,
)

UpdateHook = Callable[[GoalSnapshot | None, GoalChange], None]
MIN_WALL_CLOCK_BUDGET_MS = 1_000
MAX_WALL_CLOCK_BUDGET_MS = 24 * 60 * 60 * 1_000


class GoalService:
    def __init__(self, on_update: UpdateHook | None = None) -> None:
        self._state: GoalState | None = None
        self._queue = GoalQueue()
        self._on_update = on_update
        self._turn_counted = False
        self._last_promoted: GoalQueueItem | None = None

    @property
    def state(self) -> GoalState | None:
        return self._state

    def snapshot(self) -> GoalSnapshot | None:
        return None if self._state is None else self._state.snapshot()

    def queue_items(self) -> list[GoalQueueItem]:
        return list(self._queue.items)

    def dump(self) -> GoalDump:
        return dump_goal(self._state, self._queue)

    def restore(self, goal: dict[str, Any] | None, queue: object = None) -> None:
        self._state = state_from_dict(goal)
        self._queue = load_queue(queue)
        self._turn_counted = False
        self._last_promoted = None

    def assert_mode_allows_run(self, mode: str) -> None:
        normalized = (mode or "agent").strip() or "agent"
        if normalized not in ALLOWED_GOAL_MODES:
            raise GoalError(
                "mode_not_allowed",
                f"Goal mode cannot run in {normalized} mode. Switch to agent first.",
            )

    def create(
        self,
        objective: str,
        *,
        completion_criterion: str | None = None,
        replace: bool = False,
        actor: GoalActor = GoalActor.USER,
        mode: str = "agent",
    ) -> GoalSnapshot:
        self.assert_mode_allows_run(mode)
        if self._state is not None:
            if not replace:
                raise GoalError(
                    "already_exists",
                    "A goal already exists; use replace to start a new one",
                )
            self._clear(GoalActor.SYSTEM, emit=True)
        self._state = new_goal(objective, completion_criterion=completion_criterion)
        self._turn_counted = False
        self._last_promoted = None
        snapshot = self._state.snapshot()
        self._emit(snapshot, GoalChange(GoalChangeKind.LIFECYCLE, GoalStatus.ACTIVE, actor=actor))
        return snapshot

    def pause(
        self,
        reason: str | None = None,
        actor: GoalActor = GoalActor.USER,
    ) -> GoalSnapshot:
        state = self._require()
        if state.status is GoalStatus.PAUSED:
            return state.snapshot()
        if state.status is not GoalStatus.ACTIVE:
            raise GoalError(
                "status_invalid",
                f'Cannot pause a goal in status "{state.status.value}"',
            )
        return self._set_status(GoalStatus.PAUSED, reason or "Paused by user", actor)

    def resume(
        self,
        reason: str | None = None,
        actor: GoalActor = GoalActor.USER,
        *,
        mode: str = "agent",
        launch: bool = True,
    ) -> tuple[GoalSnapshot, ContinuationDecision]:
        self.assert_mode_allows_run(mode)
        state = self._require()
        if state.status is GoalStatus.ACTIVE:
            return state.snapshot(), self.peek_continuation(mode=mode)
        if state.status not in (GoalStatus.PAUSED, GoalStatus.BLOCKED):
            raise GoalError(
                "not_resumable",
                f'Cannot resume a goal in status "{state.status.value}"',
            )
        snapshot = self._set_status(GoalStatus.ACTIVE, reason, actor)
        blocked = self._block_if_budget_reached(actor=GoalActor.RUNTIME)
        if blocked is not None:
            return blocked, ContinuationDecision(False, reason="budget")
        decision = (
            self.peek_continuation(mode=mode)
            if launch
            else ContinuationDecision(False, reason="no_launch")
        )
        return snapshot, decision

    def cancel(self, actor: GoalActor = GoalActor.USER) -> GoalSnapshot:
        state = self._require()
        snapshot = state.snapshot()
        self._clear(actor, emit=True)
        return snapshot

    def mark_complete(
        self,
        reason: str | None = None,
        actor: GoalActor = GoalActor.MODEL,
    ) -> tuple[GoalSnapshot, GoalQueueItem | None]:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            raise GoalError("not_found", "No active goal")
        completed = apply_status(state, GoalStatus.COMPLETE, reason=reason)
        snapshot = completed.snapshot()
        self._emit(
            snapshot,
            GoalChange(
                GoalChangeKind.COMPLETION,
                GoalStatus.COMPLETE,
                reason,
                actor,
            ),
        )
        self._clear(actor, emit=True)
        promoted = self._queue.peek_next()
        self._last_promoted = promoted
        return snapshot, promoted

    def consume_promoted(self) -> GoalQueueItem | None:
        item = self._last_promoted
        self._last_promoted = None
        if item is None:
            return None
        current = self._queue.peek_next()
        if current is None or current.item_id != item.item_id:
            return None
        return item

    def acknowledge_promoted(self, item_id: str) -> None:
        if self._queue.remove_item(item_id) is None:
            return
        snapshot = self.snapshot()
        self._emit(
            snapshot,
            GoalChange(
                GoalChangeKind.PROGRESS,
                None if snapshot is None else snapshot.status,
                actor=GoalActor.RUNTIME,
            ),
        )

    def discard_promoted(self) -> None:
        self._last_promoted = None

    def mark_blocked(
        self,
        reason: str | None = None,
        actor: GoalActor = GoalActor.MODEL,
    ) -> GoalSnapshot:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            raise GoalError("not_found", "No active goal")
        return self._set_status(GoalStatus.BLOCKED, reason or "Blocked", actor)

    def set_budget(
        self,
        *,
        token_budget: int | None = None,
        turn_budget: int | None = None,
        wall_clock_budget_ms: int | None = None,
        actor: GoalActor = GoalActor.USER,
    ) -> GoalSnapshot:
        state = self._require()
        provided = [
            value
            for value in (token_budget, turn_budget, wall_clock_budget_ms)
            if value is not None
        ]
        if not provided:
            raise GoalError("budget_empty", "Provide at least one goal budget")
        if token_budget is not None and token_budget <= 0:
            raise GoalError("budget_invalid", "Token budget must be a positive integer")
        if turn_budget is not None and turn_budget <= 0:
            raise GoalError("budget_invalid", "Turn budget must be a positive integer")
        if wall_clock_budget_ms is not None and not (
            MIN_WALL_CLOCK_BUDGET_MS
            <= wall_clock_budget_ms
            <= MAX_WALL_CLOCK_BUDGET_MS
        ):
            raise GoalError(
                "budget_invalid",
                "Wall-clock budget must be between 1000ms and 24 hours",
            )
        extra = GoalBudgetLimits(
            token_budget=token_budget,
            turn_budget=turn_budget,
            wall_clock_budget_ms=wall_clock_budget_ms,
        )
        self._state = replace(state, budget_limits=state.budget_limits.merged(extra))
        blocked = self._block_if_budget_reached(actor=GoalActor.RUNTIME)
        if blocked is not None:
            return blocked
        snapshot = self._state.snapshot()
        self._emit(snapshot, GoalChange(GoalChangeKind.LIFECYCLE, snapshot.status, actor=actor))
        return snapshot

    def enqueue(self, objective: str) -> GoalQueueItem:
        return self._queue.add(objective)

    def queue_remove(self, index: int) -> GoalQueueItem:
        return self._queue.remove(index)

    def queue_move(self, src: int, dest: int) -> None:
        self._queue.move(src, dest)

    def format_queue(self) -> str:
        if not self._queue.items:
            return "No upcoming goals."
        lines = ["Upcoming goals (hidden from the agent until the current goal completes):"]
        for idx, item in enumerate(self._queue.items, start=1):
            lines.append(f"{idx}. {item.objective}")
        return "\n".join(lines)

    def on_turn_started(self) -> GoalSnapshot | None:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            self._turn_counted = False
            return None
        blocked = self._block_if_budget_reached(actor=GoalActor.RUNTIME)
        if blocked is not None:
            return blocked
        self.adopt_current_turn()
        return None if self._state is None else self._state.snapshot()

    def adopt_current_turn(self) -> GoalSnapshot | None:
        """Count this live turn once if a goal became active mid-turn."""
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE or self._turn_counted:
            return None if state is None else state.snapshot()
        self._state = replace(state, turns_used=state.turns_used + 1)
        self._turn_counted = True
        snapshot = self._state.snapshot()
        self._emit(
            snapshot,
            GoalChange(
                GoalChangeKind.PROGRESS,
                GoalStatus.ACTIVE,
                actor=GoalActor.RUNTIME,
            ),
        )
        return snapshot

    def account_tokens(self, output_tokens: int) -> GoalSnapshot | None:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            return None
        delta = max(0, int(output_tokens))
        if delta:
            self._state = replace(state, tokens_used=state.tokens_used + delta)
        blocked = self._block_if_budget_reached(
            actor=GoalActor.RUNTIME,
            include_turn=False,
        )
        if blocked is not None:
            return blocked
        if delta:
            snapshot = self._state.snapshot()
            self._emit(
                snapshot,
                GoalChange(
                    GoalChangeKind.PROGRESS,
                    GoalStatus.ACTIVE,
                    actor=GoalActor.RUNTIME,
                ),
            )
        return None

    def on_turn_ended(
        self,
        *,
        cancelled: bool = False,
        failed: bool = False,
        error_message: str | None = None,
        output_tokens: int = 0,
        mode: str = "agent",
    ) -> ContinuationDecision:
        self.account_tokens(output_tokens)
        self._turn_counted = False
        state = self._state
        if state is None:
            return ContinuationDecision(False, reason="none")
        if cancelled and state.status is GoalStatus.ACTIVE:
            self._set_status(GoalStatus.PAUSED, "Paused after interruption", GoalActor.USER)
            return ContinuationDecision(False, reason="paused")
        if failed and state.status is GoalStatus.ACTIVE:
            reason = "Paused after runtime error"
            if error_message:
                reason = f"{reason}: {error_message}"
            self._set_status(GoalStatus.PAUSED, reason, GoalActor.RUNTIME)
            return ContinuationDecision(False, reason="paused")
        if state.status is not GoalStatus.ACTIVE:
            return ContinuationDecision(False, reason=state.status.value)
        blocked = self._block_if_budget_reached(actor=GoalActor.RUNTIME)
        if blocked is not None:
            return ContinuationDecision(False, reason="budget")
        normalized_mode = (mode or "agent").strip() or "agent"
        if normalized_mode not in ALLOWED_GOAL_MODES:
            self._set_status(
                GoalStatus.PAUSED,
                f"Paused after mode changed to {normalized_mode}",
                GoalActor.RUNTIME,
            )
            return ContinuationDecision(False, reason="mode")
        return self.peek_continuation(mode=normalized_mode)

    def peek_continuation(self, *, mode: str = "agent") -> ContinuationDecision:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            return ContinuationDecision(False, reason="inactive")
        normalized_mode = (mode or "agent").strip() or "agent"
        if normalized_mode not in ALLOWED_GOAL_MODES:
            return ContinuationDecision(False, reason="mode")
        if state.snapshot().budget.over_budget:
            return ContinuationDecision(False, reason="budget")
        return ContinuationDecision(True, prompt=GOAL_CONTINUATION_PROMPT, reason="active")

    def reminder_text(self) -> str:
        snapshot = self.snapshot()
        if snapshot is None:
            return ""
        return reminder_body(snapshot)

    def format_status(self) -> str:
        snapshot = self.snapshot()
        if snapshot is None:
            queued = self.format_queue()
            if queued == "No upcoming goals.":
                return "No current goal."
            return f"No current goal.\n\n{queued}"
        lines = [
            f"Status: {snapshot.status.value}",
            f"Objective: {snapshot.objective}",
        ]
        if snapshot.completion_criterion:
            lines.append(f"Done when: {snapshot.completion_criterion}")
        if snapshot.terminal_reason:
            lines.append(f"Reason: {snapshot.terminal_reason}")
        lines.append(
            f"Progress: {snapshot.turns_used} turns, {snapshot.tokens_used} tokens, "
            f"{snapshot.wall_clock_ms}ms"
        )
        budget = snapshot.budget
        if budget.turn_budget or budget.token_budget or budget.wall_clock_budget_ms:
            lines.append(
                "Budget: "
                f"turns {snapshot.turns_used}/{budget.turn_budget or '—'} · "
                f"tokens {snapshot.tokens_used}/{budget.token_budget or '—'} · "
                f"time {snapshot.wall_clock_ms}/{budget.wall_clock_budget_ms or '—'}ms"
            )
        queued = self.format_queue()
        if queued != "No upcoming goals.":
            lines.append("")
            lines.append(queued)
        return "\n".join(lines)

    def _set_status(self, status: GoalStatus, reason: str | None, actor: GoalActor) -> GoalSnapshot:
        state = self._require()
        self._state = apply_status(state, status, reason=reason)
        snapshot = self._state.snapshot()
        self._emit(snapshot, GoalChange(GoalChangeKind.LIFECYCLE, status, reason, actor))
        return snapshot

    def _block_if_budget_reached(
        self,
        *,
        actor: GoalActor,
        include_turn: bool = True,
    ) -> GoalSnapshot | None:
        state = self._state
        if state is None or state.status is not GoalStatus.ACTIVE:
            return None
        report = compute_budget_report(
            state.budget_limits,
            state.tokens_used,
            state.turns_used,
            state.live_wall_clock_ms(),
        )
        if report.turn_budget_reached and not include_turn:
            report = replace(
                report,
                turn_budget_reached=False,
                over_budget=(
                    report.token_budget_reached
                    or report.wall_clock_budget_reached
                ),
            )
        reason = budget_block_reason(report)
        if reason is None:
            return None
        return self._set_status(GoalStatus.BLOCKED, reason, actor)

    def _clear(self, actor: GoalActor, *, emit: bool) -> None:
        self._state = None
        self._turn_counted = False
        if emit:
            self._emit(None, GoalChange(GoalChangeKind.CLEARED, actor=actor))

    def _require(self) -> GoalState:
        if self._state is None:
            raise GoalError("not_found", "No current goal")
        return self._state

    def _emit(self, snapshot: GoalSnapshot | None, change: GoalChange) -> None:
        if self._on_update is not None:
            self._on_update(snapshot, change)
