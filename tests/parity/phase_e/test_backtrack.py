"""Backtrack state machine parity tests.

Mirror Rust tests in ``crates/tui/src/tui/backtrack.rs`` (backtrack.rs:198+).
"""

from __future__ import annotations

from deepseek_tui.tui.backtrack import (
    BacktrackPhase,
    BacktrackState,
    Direction,
    EscEffect,
)


def test_new_state_is_inactive() -> None:
    """Mirror Rust ``new_state_is_inactive`` (backtrack.rs:201)."""
    s = BacktrackState()
    assert not s.is_active()
    assert not s.is_selecting()
    assert s.get_selected_idx() is None


def test_first_esc_primes() -> None:
    """Mirror Rust ``first_esc_primes`` (backtrack.rs:209)."""
    s = BacktrackState()
    assert s.handle_esc(3) == EscEffect.PRIME
    assert s.phase == BacktrackPhase.PRIMED
    assert s.is_active()
    assert not s.is_selecting()


def test_first_esc_with_no_user_messages_is_noop() -> None:
    """Mirror Rust ``first_esc_with_no_user_messages_is_noop`` (backtrack.rs:219)."""
    s = BacktrackState()
    assert s.handle_esc(0) == EscEffect.NONE
    assert s.phase == BacktrackPhase.INACTIVE


def test_double_esc_enters_selecting() -> None:
    """Mirror Rust ``double_esc_enters_selecting`` (backtrack.rs:227)."""
    s = BacktrackState()
    assert s.handle_esc(5) == EscEffect.PRIME
    assert s.handle_esc(5) == EscEffect.OPEN_OVERLAY
    assert s.phase == BacktrackPhase.SELECTING
    assert s.selected_idx == 0
    assert s.total == 5
    assert s.is_selecting()


def test_primed_with_zero_messages_cancels() -> None:
    """Mirror Rust ``primed_with_zero_messages_cancels`` (backtrack.rs:243)."""
    s = BacktrackState()
    s.phase = BacktrackPhase.PRIMED
    assert s.handle_esc(0) == EscEffect.CANCEL
    assert s.phase == BacktrackPhase.INACTIVE


def test_step_left_walks_back_in_time() -> None:
    """Mirror Rust ``step_left_walks_back_in_time`` (backtrack.rs:255)."""
    s = BacktrackState(phase=BacktrackPhase.SELECTING, selected_idx=0, total=3)
    s.step(Direction.LEFT)
    assert s.get_selected_idx() == 1
    s.step(Direction.LEFT)
    assert s.get_selected_idx() == 2
    s.step(Direction.LEFT)
    assert s.get_selected_idx() == 2


def test_step_right_walks_forward_in_time() -> None:
    """Mirror Rust ``step_right_walks_forward_in_time`` (backtrack.rs:271)."""
    s = BacktrackState(phase=BacktrackPhase.SELECTING, selected_idx=2, total=3)
    s.step(Direction.RIGHT)
    assert s.get_selected_idx() == 1
    s.step(Direction.RIGHT)
    assert s.get_selected_idx() == 0
    s.step(Direction.RIGHT)
    assert s.get_selected_idx() == 0


def test_confirm_returns_selected_and_resets() -> None:
    """Mirror Rust ``confirm_returns_selected_and_resets``."""
    s = BacktrackState(phase=BacktrackPhase.SELECTING, selected_idx=2, total=5)
    assert s.confirm() == 2
    assert s.phase == BacktrackPhase.INACTIVE
    assert s.confirm() is None


def test_reset_returns_to_inactive() -> None:
    """Mirror Rust ``reset_returns_to_inactive``."""
    s = BacktrackState(phase=BacktrackPhase.SELECTING, selected_idx=1, total=4)
    s.reset()
    assert s.phase == BacktrackPhase.INACTIVE
    assert s.selected_idx == 0
    assert s.total == 0


def test_step_in_inactive_is_noop() -> None:
    s = BacktrackState()
    s.step(Direction.LEFT)
    assert s.phase == BacktrackPhase.INACTIVE
    assert s.selected_idx == 0


def test_step_with_total_zero_is_noop() -> None:
    s = BacktrackState(phase=BacktrackPhase.SELECTING, selected_idx=0, total=0)
    s.step(Direction.LEFT)
    assert s.selected_idx == 0
    s.step(Direction.RIGHT)
    assert s.selected_idx == 0


def test_third_esc_in_selecting_cancels() -> None:
    """Defensive — Esc routed back through state machine while selecting."""
    s = BacktrackState(phase=BacktrackPhase.SELECTING, selected_idx=1, total=3)
    assert s.handle_esc(3) == EscEffect.CANCEL
    assert s.phase == BacktrackPhase.INACTIVE
