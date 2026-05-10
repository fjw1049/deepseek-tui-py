"""Plan prompt state machine parity tests.

Mirror Rust tests in ``crates/tui/src/tui/plan_prompt.rs`` (plan_prompt.rs:256-291).
"""

from __future__ import annotations

from deepseek_tui.tui.plan_prompt import PLAN_OPTIONS, PlanOutcome, PlanPromptState


def test_default_selection_is_first_option() -> None:
    s = PlanPromptState()
    assert s.selected == 0
    assert s.submit() == PlanOutcome.ACCEPT_AGENT


def test_move_down_clamps_at_max_index() -> None:
    s = PlanPromptState()
    for _ in range(10):
        s.move_down()
    assert s.selected == s.max_index()


def test_move_up_clamps_at_zero() -> None:
    s = PlanPromptState(selected=2)
    for _ in range(10):
        s.move_up()
    assert s.selected == 0


def test_submit_number_1_through_4_picks_option() -> None:
    """Mirror Rust ``KeyCode::Char('1')`` … ``Char('4')`` (plan_prompt.rs:148-163)."""
    s = PlanPromptState()
    assert s.submit_number(1) == PlanOutcome.ACCEPT_AGENT
    assert s.submit_number(2) == PlanOutcome.ACCEPT_YOLO
    assert s.submit_number(3) == PlanOutcome.REVISE
    assert s.submit_number(4) == PlanOutcome.EXIT_PLAN


def test_submit_number_out_of_range_returns_none() -> None:
    s = PlanPromptState()
    assert s.submit_number(0) is None
    assert s.submit_number(5) is None
    assert s.submit_number(-1) is None


def test_submit_letter_a_picks_first() -> None:
    """Mirror Rust ``KeyCode::Char('a')`` (plan_prompt.rs:164)."""
    s = PlanPromptState()
    assert s.submit_letter("a") == PlanOutcome.ACCEPT_AGENT
    assert s.submit_letter("A") == PlanOutcome.ACCEPT_AGENT


def test_submit_letter_y_picks_yolo() -> None:
    s = PlanPromptState()
    assert s.submit_letter("y") == PlanOutcome.ACCEPT_YOLO
    assert s.submit_letter("Y") == PlanOutcome.ACCEPT_YOLO


def test_submit_letter_r_picks_revise() -> None:
    s = PlanPromptState()
    assert s.submit_letter("r") == PlanOutcome.REVISE


def test_submit_letter_q_or_e_picks_exit() -> None:
    s = PlanPromptState()
    assert s.submit_letter("q") == PlanOutcome.EXIT_PLAN
    assert s.submit_letter("Q") == PlanOutcome.EXIT_PLAN
    assert s.submit_letter("e") == PlanOutcome.EXIT_PLAN
    assert s.submit_letter("E") == PlanOutcome.EXIT_PLAN


def test_submit_letter_invalid_returns_none() -> None:
    s = PlanPromptState()
    assert s.submit_letter("z") is None
    assert s.submit_letter("") is None


def test_options_match_rust_order() -> None:
    """Mirror Rust ``PLAN_OPTIONS`` (plan_prompt.rs:11)."""
    labels = [label for _, label, _ in PLAN_OPTIONS]
    assert labels == [
        "Accept plan (Agent)",
        "Accept plan (YOLO)",
        "Revise plan",
        "Exit Plan mode",
    ]
