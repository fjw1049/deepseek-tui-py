"""Goal state machine and restore-to-paused."""

from __future__ import annotations

import pytest

from deepseek_tui.goal.persist import state_from_dict, state_to_dict
from deepseek_tui.goal.state import apply_status, new_goal, restore_pause
from deepseek_tui.goal.types import RESUME_AFTER_RESTORE_REASON, GoalError, GoalStatus


def test_new_goal_is_active() -> None:
    state = new_goal("Ship the feature")
    snap = state.snapshot()
    assert snap.status is GoalStatus.ACTIVE
    assert snap.objective == "Ship the feature"
    assert snap.turns_used == 0
    assert snap.tokens_used == 0
    assert not snap.budget.over_budget


def test_reject_empty_or_too_long_objective() -> None:
    with pytest.raises(GoalError) as exc:
        new_goal("   ")
    assert exc.value.code == "objective_empty"
    with pytest.raises(GoalError) as exc:
        new_goal("x" * 4001)
    assert exc.value.code == "objective_too_long"


def test_pause_and_resume_status() -> None:
    state = new_goal("Ship it")
    paused = apply_status(state, GoalStatus.PAUSED, reason="Paused by user")
    assert paused.status is GoalStatus.PAUSED
    assert paused.terminal_reason == "Paused by user"
    resumed = apply_status(paused, GoalStatus.ACTIVE)
    assert resumed.status is GoalStatus.ACTIVE
    assert resumed.terminal_reason is None


def test_restore_downgrades_active_to_paused() -> None:
    state = new_goal("Keep going")
    restored = restore_pause(state)
    assert restored.status is GoalStatus.PAUSED
    assert restored.terminal_reason == RESUME_AFTER_RESTORE_REASON
    assert restored.live_started_mono is None


def test_restore_leaves_blocked_and_paused() -> None:
    paused = apply_status(new_goal("x"), GoalStatus.PAUSED, reason="manual")
    assert restore_pause(paused).status is GoalStatus.PAUSED
    blocked = apply_status(new_goal("x"), GoalStatus.BLOCKED, reason="stuck")
    restored = restore_pause(blocked)
    assert restored.status is GoalStatus.BLOCKED
    assert restored.terminal_reason == "stuck"


def test_persist_roundtrip_pauses_active() -> None:
    dumped = state_to_dict(new_goal("Persist me"))
    loaded = state_from_dict(dumped)
    assert loaded is not None
    assert loaded.status is GoalStatus.PAUSED
    assert loaded.terminal_reason == RESUME_AFTER_RESTORE_REASON
    assert loaded.objective == "Persist me"


def test_complete_snapshot_is_not_restored() -> None:
    completed = apply_status(new_goal("done"), GoalStatus.COMPLETE, reason="finished")
    assert state_from_dict(state_to_dict(completed)) is None
