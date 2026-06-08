"""Full Goal lifecycle test — simulates TUI /goal command interactions.

Tests the complete create → continuation → budget limit → pause → resume → complete chain,
verifying all P0 fixes are working correctly.
"""

from __future__ import annotations

import pytest

from deepseek_tui.goal.controller import GoalController
from deepseek_tui.goal.models import GoalStatus
from deepseek_tui.protocol.responses import Usage


# ─── Query 1: Goal Full Lifecycle ─────────────────────────────────────────────
#
# Simulates: user opens TUI → /goal create "Build auth system" --budget 80000
# → agent works multiple turns → budget approaches limit → budget reached
# → user resumes with new budget → completes
#


class TestGoalCreateAndAutoContinuation:
    """After /goal create, agent must immediately start working."""

    def test_create_queues_follow_up(self, tmp_path) -> None:
        """Create goal → pending follow-up is queued for engine consumption."""
        ctrl = GoalController(tmp_path, "t1")
        ctrl.create("Build JWT auth with login/logout endpoints")

        follow_up = ctrl.take_pending_follow_up()
        assert follow_up is not None
        assert "Build JWT auth" in follow_up.content
        assert follow_up.goal_id == ctrl.current.goal_id

    def test_create_rejects_overwrite_without_flag(self, tmp_path) -> None:
        """/goal create while active goal exists → error."""
        ctrl = GoalController(tmp_path, "t2")
        ctrl.create("first goal")

        with pytest.raises(ValueError, match="replace_existing"):
            ctrl.create("second goal")

    def test_create_with_replace_existing(self, tmp_path) -> None:
        """/goal create --replace succeeds and queues new follow-up."""
        ctrl = GoalController(tmp_path, "t3")
        first = ctrl.create("first")
        ctrl.create("replacement", replace_existing=True)

        assert ctrl.current.objective == "replacement"
        assert ctrl.current.goal_id != first.goal_id
        follow_up = ctrl.take_pending_follow_up()
        assert follow_up is not None
        assert follow_up.goal_id == ctrl.current.goal_id


class TestGoalAutoContinuationChain:
    """Each successful turn auto-schedules the next continuation."""

    def test_turn_complete_schedules_next(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "chain")
        ctrl.create("multi-turn task")
        ctrl.take_pending_follow_up()  # consume initial

        # Simulate turn 1
        ctrl.on_turn_start()
        follow_up = ctrl.on_turn_complete(Usage(input_tokens=100, output_tokens=50))
        assert follow_up is not None
        assert follow_up.goal_id == ctrl.current.goal_id

        # Simulate turn 2
        ctrl.on_turn_start()
        follow_up = ctrl.on_turn_complete(Usage(input_tokens=200, output_tokens=80))
        assert follow_up is not None

    def test_continuation_stops_when_goal_completed(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "stop")
        ctrl.create("finish quickly")
        ctrl.take_pending_follow_up()

        ctrl.complete("all done")
        assert ctrl.current.status == GoalStatus.COMPLETE
        assert ctrl.take_pending_follow_up() is None


class TestGoalBudgetLifecycle:
    """Budget tracking → limit → steer → no more continuations."""

    def test_budget_exhaustion_flow(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "budget")
        ctrl.create("stay within budget", token_budget=5000)
        ctrl.take_pending_follow_up()

        # Turn 1: uses 2000 tokens
        ctrl.on_turn_start()
        f1 = ctrl.on_turn_complete(Usage(input_tokens=1200, output_tokens=800))
        assert f1 is not None  # still under budget → continue
        assert ctrl.current.usage.tokens_used == 2000

        # Turn 2: uses 2000 tokens (total 4000, still under)
        ctrl.on_turn_start()
        f2 = ctrl.on_turn_complete(Usage(input_tokens=1000, output_tokens=1000))
        assert f2 is not None
        assert ctrl.current.usage.tokens_used == 4000

        # Turn 3: uses 1500 tokens (total 5500, over budget!)
        ctrl.on_turn_start()
        f3 = ctrl.on_turn_complete(Usage(input_tokens=800, output_tokens=700))
        assert f3 is None  # no more follow-ups
        assert ctrl.current.status == GoalStatus.BUDGET_LIMITED

        # Steer message queued
        steer = ctrl.take_pending_steer()
        assert steer is not None
        assert "budget" in steer.lower()

    def test_budget_limited_cannot_resume(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "no-resume")
        ctrl.create("limited", token_budget=1000)
        ctrl.on_turn_start()
        ctrl.on_turn_complete(Usage(input_tokens=600, output_tokens=500))

        assert ctrl.current.status == GoalStatus.BUDGET_LIMITED
        with pytest.raises(ValueError, match="budget"):
            ctrl.resume()


class TestGoalUserCancel:
    """User pressing Ctrl+C → immediate pause, not failure counting."""

    def test_user_cancel_immediate_pause(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "cancel")
        ctrl.create("long task")
        ctrl.take_pending_follow_up()

        ctrl.on_turn_start()
        ctrl.on_turn_failed("user_cancelled")

        assert ctrl.current.status == GoalStatus.PAUSED
        assert ctrl.current.reason == "user cancelled"
        # Only 1 cancel, should already be paused (not waiting for 3)
        assert ctrl.take_pending_follow_up() is None

    def test_transient_failures_still_count(self, tmp_path) -> None:
        """Non-cancel failures use the 3-strike rule."""
        ctrl = GoalController(tmp_path, "transient")
        ctrl.create("fragile task")

        ctrl.on_turn_failed("network_error")
        assert ctrl.current.status == GoalStatus.ACTIVE  # 1st fail, still active

        ctrl.on_turn_failed("network_error")
        assert ctrl.current.status == GoalStatus.ACTIVE  # 2nd fail

        ctrl.on_turn_failed("network_error")
        assert ctrl.current.status == GoalStatus.PAUSED  # 3rd → paused


class TestGoalResumeTriggersWork:
    """/goal resume must queue a follow-up so agent resumes."""

    def test_resume_queues_follow_up(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "resume")
        ctrl.create("pausable task")
        ctrl.take_pending_follow_up()

        ctrl.pause("taking a break")
        assert ctrl.current.status == GoalStatus.PAUSED
        assert ctrl.take_pending_follow_up() is None

        ctrl.resume()
        assert ctrl.current.status == GoalStatus.ACTIVE
        follow_up = ctrl.take_pending_follow_up()
        assert follow_up is not None
        assert follow_up.goal_id == ctrl.current.goal_id


class TestGoalPersistenceAndRebind:
    """Goal survives session restart via journal."""

    def test_journal_persists_and_restores(self, tmp_path) -> None:
        # Session 1: create and use
        ctrl1 = GoalController(tmp_path, "persist")
        ctrl1.create("durable goal", token_budget=50000)
        ctrl1.on_turn_start()
        ctrl1.on_turn_complete(Usage(input_tokens=100, output_tokens=50))
        goal_id = ctrl1.current.goal_id

        # Session 2: new controller, same workspace/thread
        ctrl2 = GoalController(tmp_path, "persist")
        assert ctrl2.current is not None
        assert ctrl2.current.goal_id == goal_id
        assert ctrl2.current.objective == "durable goal"
        assert ctrl2.current.usage.tokens_used == 150
        assert ctrl2.current.status == GoalStatus.ACTIVE

    def test_rebind_to_different_thread(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "thread-a")
        ctrl.create("goal A")

        ctrl.rebind(thread_id="thread-b")
        assert ctrl.current is None  # thread-b has no goal

        ctrl.rebind(thread_id="thread-a")
        assert ctrl.current is not None
        assert ctrl.current.objective == "goal A"


class TestGoalStaleFollowUpGuard:
    """Stale follow-ups from replaced/cleared goals are rejected."""

    def test_stale_after_clear(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "stale-clear")
        goal = ctrl.create("will be cleared")
        ctrl.on_turn_start()
        ctrl.on_turn_complete(Usage(input_tokens=1, output_tokens=1))
        # follow-up is pending for old goal
        ctrl.clear()

        assert ctrl.take_pending_follow_up() is None
        assert not ctrl.validate_follow_up(goal.goal_id)

    def test_stale_after_replace(self, tmp_path) -> None:
        ctrl = GoalController(tmp_path, "stale-replace")
        first = ctrl.create("first")
        ctrl.on_turn_start()
        ctrl.on_turn_complete(Usage(input_tokens=1, output_tokens=1))

        ctrl.create("second", replace_existing=True)
        assert not ctrl.validate_follow_up(first.goal_id)
        # New follow-up should be for the new goal
        pending = ctrl.take_pending_follow_up()
        assert pending.goal_id == ctrl.current.goal_id
