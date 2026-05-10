"""Frame rate limiter parity tests.

Mirror Rust tests in ``crates/tui/src/tui/frame_rate_limiter.rs``.
"""

from __future__ import annotations

from deepseek_tui.tui.frame_rate_limiter import (
    LOW_MOTION_MIN_FRAME_INTERVAL_SECS,
    MIN_FRAME_INTERVAL_SECS,
    FrameRateLimiter,
)


def test_default_does_not_clamp() -> None:
    """Mirror Rust ``default_does_not_clamp`` (frame_rate_limiter.rs:101)."""
    t0 = 100.0
    limiter = FrameRateLimiter()
    assert limiter.clamp_deadline(t0) == t0
    assert limiter.time_until_next_draw(t0) is None


def test_clamps_to_min_interval_since_last_emit() -> None:
    """Mirror Rust ``clamps_to_min_interval_since_last_emit`` (frame_rate_limiter.rs:109)."""
    t0 = 100.0
    limiter = FrameRateLimiter()
    assert limiter.clamp_deadline(t0) == t0
    limiter.mark_emitted(t0)

    too_soon = t0 + 0.001
    assert limiter.clamp_deadline(too_soon) == t0 + MIN_FRAME_INTERVAL_SECS


def test_time_until_next_draw_reports_remaining_window() -> None:
    """Mirror Rust ``time_until_next_draw_reports_remaining_window``."""
    t0 = 100.0
    limiter = FrameRateLimiter()
    limiter.mark_emitted(t0)

    after_4ms = t0 + 0.004
    remaining = limiter.time_until_next_draw(after_4ms)
    assert remaining is not None
    assert 0.004 < remaining < 0.005


def test_time_until_next_draw_none_after_interval_elapsed() -> None:
    t0 = 100.0
    limiter = FrameRateLimiter()
    limiter.mark_emitted(t0)
    assert limiter.time_until_next_draw(t0 + 0.05) is None


def test_low_motion_clamps_to_30fps_interval() -> None:
    """Mirror Rust ``low_motion_clamps_to_30fps_interval`` (frame_rate_limiter.rs:146)."""
    t0 = 100.0
    limiter = FrameRateLimiter()
    limiter.set_low_motion(True)
    limiter.mark_emitted(t0)

    too_soon = t0 + 0.005
    assert limiter.clamp_deadline(too_soon) == t0 + LOW_MOTION_MIN_FRAME_INTERVAL_SECS

    after_34 = t0 + 0.034
    assert limiter.time_until_next_draw(after_34) is None


def test_low_motion_switching_respects_current_mode() -> None:
    t0 = 100.0
    limiter = FrameRateLimiter()
    limiter.mark_emitted(t0)
    t10 = t0 + 0.010
    assert limiter.time_until_next_draw(t10) is None

    limiter.set_low_motion(True)
    limiter.mark_emitted(t10)
    t20 = t10 + 0.010
    remaining = limiter.time_until_next_draw(t20)
    assert remaining is not None
    assert 0.020 < remaining < 0.025
