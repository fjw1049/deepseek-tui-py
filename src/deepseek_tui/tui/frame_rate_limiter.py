"""Frame-rate limiter for the TUI render loop.

Mirrors ``crates/tui/src/tui/frame_rate_limiter.rs`` (186 LOC).

When the model streams a long assistant response, every SSE chunk would
fire a redraw. The user can't perceive frames faster than ~120 FPS, and
ratatui/Textual diff-and-flush has real cost, so capping the redraw rate
is a strict performance win.

In Python/Textual, the integration is conceptually the same as Rust: the
caller marks a draw event, then asks the limiter how long to wait before
the next draw is allowed. The implementation is monotonic-time based and
agnostic to the UI framework.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_FRAME_INTERVAL_SECS: float = 1.0 / 120.0
LOW_MOTION_MIN_FRAME_INTERVAL_SECS: float = 1.0 / 30.0


@dataclass(slots=True)
class FrameRateLimiter:
    """Remembers the most recent emitted draw, allowing deadlines to be clamped.

    Mirror Rust ``FrameRateLimiter`` (frame_rate_limiter.rs:44).
    """

    last_emitted_at: float | None = None
    low_motion: bool = False

    def _interval(self) -> float:
        return (
            LOW_MOTION_MIN_FRAME_INTERVAL_SECS
            if self.low_motion
            else MIN_FRAME_INTERVAL_SECS
        )

    def clamp_deadline(self, requested: float) -> float:
        """Return *requested*, clamped forward if it would exceed the cap.

        Mirror Rust ``clamp_deadline`` (frame_rate_limiter.rs:55).
        """
        last = self.last_emitted_at
        if last is None:
            return requested
        min_allowed = last + self._interval()
        return max(requested, min_allowed)

    def mark_emitted(self, emitted_at: float) -> None:
        """Record a draw was emitted at *emitted_at* (monotonic seconds)."""
        self.last_emitted_at = emitted_at

    def time_until_next_draw(self, now: float) -> float | None:
        """Seconds until next draw allowed; None if allowed now.

        Mirror Rust ``time_until_next_draw`` (frame_rate_limiter.rs:74).
        """
        clamped = self.clamp_deadline(now)
        if clamped <= now:
            return None
        return clamped - now

    def set_low_motion(self, low_motion: bool) -> None:
        """Toggle low-motion mode (30 FPS instead of 120 FPS)."""
        self.low_motion = low_motion
