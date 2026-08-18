"""GoalService lifecycle, continuation, budget, and queue promotion."""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from deepseek_tui.goal.injection import GOAL_CONTINUATION_PROMPT
from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.types import RESUME_AFTER_RESTORE_REASON, GoalError, GoalStatus


def test_create_rejects_without_replace() -> None:
    service = GoalService()
    service.create("first")
    with pytest.raises(GoalError) as exc:
        service.create("second")
    assert exc.value.code == "already_exists"
    service.create("second", replace=True)
    assert service.snapshot() is not None
    assert service.snapshot().objective == "second"


def test_ask_and_plan_cannot_create_or_resume() -> None:
    service = GoalService()
    with pytest.raises(GoalError) as exc:
        service.create("nope", mode="ask")
    assert exc.value.code == "mode_not_allowed"
    service.create("ok", mode="agent")
    service.pause()
    with pytest.raises(GoalError) as exc:
        service.resume(mode="plan")
    assert exc.value.code == "mode_not_allowed"


def test_turn_end_continues_only_while_active() -> None:
    service = GoalService()
    service.create("keep going")
    decision = service.on_turn_ended()
    assert decision.should_continue
    assert decision.prompt == GOAL_CONTINUATION_PROMPT
    service.pause()
    assert not service.on_turn_ended().should_continue


def test_technical_failure_pauses() -> None:
    service = GoalService()
    service.create("keep going")
    decision = service.on_turn_ended(failed=True, error_message="429 rate limit")
    assert not decision.should_continue
    snap = service.snapshot()
    assert snap is not None
    assert snap.status is GoalStatus.PAUSED
    assert "429" in (snap.terminal_reason or "")


def test_interrupt_pauses() -> None:
    service = GoalService()
    service.create("keep going")
    decision = service.on_turn_ended(cancelled=True)
    assert not decision.should_continue
    assert service.snapshot() is not None
    assert service.snapshot().status is GoalStatus.PAUSED


def test_complete_clears_and_promotes_queue() -> None:
    service = GoalService()
    service.create("first")
    service.enqueue("second")
    snapshot, promoted = service.mark_complete(reason="done")
    assert snapshot.status is GoalStatus.COMPLETE
    assert service.snapshot() is None
    assert promoted is not None
    assert promoted.objective == "second"
    assert service.consume_promoted() is promoted
    assert [item.objective for item in service.queue_items()] == ["second"]
    service.acknowledge_promoted(promoted.item_id)
    assert service.queue_items() == []
    assert service.consume_promoted() is None


def test_pause_and_cancel_do_not_promote() -> None:
    service = GoalService()
    service.create("first")
    service.enqueue("second")
    service.pause()
    assert service.consume_promoted() is None
    service.cancel()
    assert service.snapshot() is None
    assert [item.objective for item in service.queue_items()] == ["second"]


def test_turn_budget_blocks() -> None:
    service = GoalService()
    service.create("budgeted")
    service.set_budget(turn_budget=1)
    started = service.on_turn_started()
    assert started is not None
    assert started.status is GoalStatus.ACTIVE
    assert started.turns_used == 1
    decision = service.on_turn_ended()
    blocked = service.snapshot()
    assert blocked is not None
    assert blocked.status is GoalStatus.BLOCKED
    assert not decision.should_continue
    assert not service.peek_continuation().should_continue


def test_turn_budget_does_not_stop_the_allowed_turn_mid_round() -> None:
    service = GoalService()
    service.create("budgeted")
    service.set_budget(turn_budget=1, token_budget=100)
    service.on_turn_started()
    assert service.account_tokens(10) is None
    assert service.snapshot() is not None
    assert service.snapshot().status is GoalStatus.ACTIVE
    service.on_turn_ended()
    assert service.snapshot() is not None
    assert service.snapshot().status is GoalStatus.BLOCKED


def test_token_budget_blocks() -> None:
    service = GoalService()
    service.create("budgeted")
    service.set_budget(token_budget=10)
    blocked = service.account_tokens(10)
    assert blocked is not None
    assert blocked.status is GoalStatus.BLOCKED


def test_wall_clock_budget_blocks() -> None:
    service = GoalService()
    service.create("budgeted")
    assert service._state is not None
    service._state = replace(service._state, live_started_mono=time.monotonic() - 2)
    blocked = service.set_budget(wall_clock_budget_ms=1000)
    assert blocked.status is GoalStatus.BLOCKED


def test_restore_pauses_active_goal() -> None:
    service = GoalService()
    service.create("keep going")
    service.enqueue("later")
    dumped = service.dump()
    restored = GoalService()
    restored.restore(dumped.goal, dumped.queue)
    snap = restored.snapshot()
    assert snap is not None
    assert snap.status is GoalStatus.PAUSED
    assert snap.terminal_reason == RESUME_AFTER_RESTORE_REASON
    assert [item.objective for item in restored.queue_items()] == ["later"]


def test_adopt_current_turn_counts_mid_turn_create_once() -> None:
    service = GoalService()
    assert service.on_turn_started() is None
    service.create("created mid-turn")
    snap = service.adopt_current_turn()
    assert snap is not None
    assert snap.turns_used == 1
    assert service.adopt_current_turn().turns_used == 1


def test_resume_after_budget_block_can_reblock() -> None:
    service = GoalService()
    service.create("budgeted")
    service.set_budget(turn_budget=1)
    service.on_turn_started()
    service.on_turn_ended()
    assert service.snapshot() is not None
    assert service.snapshot().status is GoalStatus.BLOCKED
    snapshot, decision = service.resume()
    assert snapshot.status is GoalStatus.BLOCKED
    assert not decision.should_continue


def test_mode_change_pauses_instead_of_continuing() -> None:
    service = GoalService()
    service.create("keep going")
    decision = service.on_turn_ended(mode="plan")
    assert not decision.should_continue
    snapshot = service.snapshot()
    assert snapshot is not None
    assert snapshot.status is GoalStatus.PAUSED
    assert snapshot.terminal_reason == "Paused after mode changed to plan"


def test_cancelled_completion_does_not_consume_queued_goal() -> None:
    service = GoalService()
    service.create("first")
    service.enqueue("second")
    _completed, promoted = service.mark_complete()
    assert promoted is not None
    service.discard_promoted()
    assert service.consume_promoted() is None
    assert [item.objective for item in service.queue_items()] == ["second"]


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({}, "budget_empty"),
        ({"token_budget": 0}, "budget_invalid"),
        ({"turn_budget": -1}, "budget_invalid"),
        ({"wall_clock_budget_ms": 999}, "budget_invalid"),
        ({"wall_clock_budget_ms": 86_400_001}, "budget_invalid"),
    ],
)
def test_budget_validation(kwargs: dict[str, int], code: str) -> None:
    service = GoalService()
    service.create("budgeted")
    with pytest.raises(GoalError) as exc:
        service.set_budget(**kwargs)
    assert exc.value.code == code
