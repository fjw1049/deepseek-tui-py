from __future__ import annotations

from deepseek_tui.goal.controller import GoalController
from deepseek_tui.goal.models import GoalStatus
from deepseek_tui.protocol.responses import Usage


def test_controller_budget_limit_stops_follow_up(tmp_path) -> None:
    controller = GoalController(tmp_path, "budget")
    controller.create("stay within budget", token_budget=1000)
    controller.on_turn_start()

    follow_up = controller.on_turn_complete(
        Usage(input_tokens=700, output_tokens=400)
    )

    assert follow_up is None
    assert controller.current is not None
    assert controller.current.status == GoalStatus.BUDGET_LIMITED


def test_controller_rejects_stale_follow_up_after_replacement(tmp_path) -> None:
    controller = GoalController(tmp_path, "stale")
    first = controller.create("first")
    controller.on_turn_start()
    planned = controller.on_turn_complete(Usage(input_tokens=1, output_tokens=1))
    assert planned is not None
    assert planned.goal_id == first.goal_id

    second = controller.create("replacement", replace_existing=True)

    assert not controller.validate_follow_up(first.goal_id)
    pending = controller.take_pending_follow_up()
    assert pending is not None
    assert pending.goal_id == second.goal_id


def test_controller_pauses_after_repeated_terminal_failures(tmp_path) -> None:
    controller = GoalController(tmp_path, "recovery")
    controller.create("recover carefully")

    controller.on_turn_failed("failed once")
    controller.on_turn_failed("failed twice")
    controller.on_turn_failed("failed three times")

    assert controller.current is not None
    assert controller.current.status == GoalStatus.PAUSED
    assert controller.current.reason == "failed three times"


def test_controller_failed_turn_accounts_usage_without_follow_up(tmp_path) -> None:
    controller = GoalController(tmp_path, "failed-usage")
    controller.create("account failures")
    controller.on_turn_start()

    controller.on_turn_failed("context_overflow", Usage(input_tokens=3, output_tokens=4))

    assert controller.current is not None
    assert controller.current.usage.tokens_used == 7
    assert controller.current.status == GoalStatus.ACTIVE
    assert controller.take_pending_follow_up() is None


def test_controller_rejects_create_without_replace(tmp_path) -> None:
    controller = GoalController(tmp_path, "replace")
    controller.create("first goal")

    try:
        controller.create("second goal")
    except ValueError as exc:
        assert "replace_existing" in str(exc)
    else:
        raise AssertionError("expected ValueError when overwriting active goal")


def test_controller_budget_limited_resume_rejected(tmp_path) -> None:
    controller = GoalController(tmp_path, "budget-resume")
    controller.create("limited", token_budget=1000)
    controller.on_turn_start()
    controller.on_turn_complete(Usage(input_tokens=600, output_tokens=500))

    assert controller.current is not None
    assert controller.current.status == GoalStatus.BUDGET_LIMITED

    try:
        controller.resume()
    except ValueError as exc:
        assert "budget" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError when resuming budget-limited goal")


def test_controller_budget_limit_queues_steer(tmp_path) -> None:
    controller = GoalController(tmp_path, "budget-steer")
    controller.create("limited", token_budget=1000)
    controller.on_turn_start()
    controller.on_turn_complete(Usage(input_tokens=600, output_tokens=500))

    steer = controller.take_pending_steer()
    assert steer is not None
    assert "token budget" in steer.lower()
