from __future__ import annotations

from pathlib import Path
from typing import Any

from deepseek_tui.goal.accounting import GoalAccounting, tokens_from_usage
from deepseek_tui.goal.continuation import GoalFollowUp, plan_follow_up
from deepseek_tui.goal.models import GoalStatus, ThreadGoal
from deepseek_tui.goal.persistence import GoalJournal
from deepseek_tui.goal.prompts import budget_limited_message
from deepseek_tui.goal.recovery import FailureAction, FailureKind, GoalRecovery, classify_failure
from deepseek_tui.goal.stale_guard import is_follow_up_stale
from deepseek_tui.goal.state import (
    apply_usage,
    clear_entry,
    set_entry,
    usage_entry,
)
from deepseek_tui.goal.transition import plan_goal_transition
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

    def _apply_status(self, request: str, *, reason: str | None = None) -> ThreadGoal | None:
        result = plan_goal_transition(self.current, request, reason=reason)  # type: ignore[arg-type]
        self.current = result.goal
        if result.persist == "set" and self.current is not None:
            self.journal.append(set_entry(self.current))
        elif result.persist == "clear" and self.current is not None:
            self.journal.append(clear_entry(self.current, reason=reason))
        if self.current is None or self.current.status != GoalStatus.ACTIVE:
            self._pending_follow_up = None
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
