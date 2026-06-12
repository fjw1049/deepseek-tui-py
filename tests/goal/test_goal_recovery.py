from __future__ import annotations

from deepseek_tui.integrations.goal import GoalController
from deepseek_tui.integrations.goal import GoalStatus
from deepseek_tui.integrations.goal import FailureAction, FailureKind, GoalRecovery, classify_failure


def test_classify_user_cancel_and_interrupt() -> None:
    assert classify_failure("user_cancelled") == FailureKind.USER_CANCEL
    assert classify_failure("interrupt_requested") == FailureKind.USER_CANCEL


def test_classify_context_overflow_and_fatal() -> None:
    assert classify_failure("context_overflow") == FailureKind.CONTEXT_OVERFLOW
    assert classify_failure("engine_error: boom") == FailureKind.FATAL


def test_recovery_overflow_waits_before_pause(tmp_path) -> None:
    controller = GoalController(tmp_path, "overflow")
    controller.create("handle overflow")

    controller.on_turn_failed("context_overflow")
    assert controller.current is not None
    assert controller.current.status == GoalStatus.ACTIVE

    controller.on_turn_failed("context_overflow")
    assert controller.current.status == GoalStatus.ACTIVE

    controller.on_turn_failed("context_overflow")
    assert controller.current.status == GoalStatus.PAUSED


def test_recovery_user_cancel_pauses_immediately(tmp_path) -> None:
    controller = GoalController(tmp_path, "cancel")
    controller.create("cancel test")

    controller.on_turn_failed("user_cancelled")

    assert controller.current is not None
    assert controller.current.status == GoalStatus.PAUSED
    assert controller.current.reason == "user cancelled"


def test_recovery_fatal_pauses_immediately(tmp_path) -> None:
    controller = GoalController(tmp_path, "fatal")
    controller.create("fatal test")

    controller.on_turn_failed("engine_error: internal")

    assert controller.current is not None
    assert controller.current.status == GoalStatus.PAUSED


def test_goal_recovery_evaluate_failure_actions() -> None:
    recovery = GoalRecovery()
    assert recovery.evaluate_failure("user_cancelled") == FailureAction.PAUSE_NOW
    assert recovery.evaluate_failure("failed") == FailureAction.COUNTED
    assert recovery.evaluate_failure("context_overflow") == FailureAction.OVERFLOW_WAIT
