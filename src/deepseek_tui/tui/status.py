"""Status bar, frame rate limiter, and OSC8 hyperlinks.
"""

from __future__ import annotations



# ======================================================================
# From widgets/status_bar.py
# ======================================================================

"""Status footer — mirrors Rust ``crates/tui/src/tui/widgets/footer.rs``.

Single 1-row bar docked to the bottom of the app, rendered as a
3-column Rich ``Table.grid`` inside one ``Static``. The earlier
``Horizontal`` + three-child approach proved brittle under Textual's
dock layout (the row vanished when stacked with ``ComposerHint`` and
``Composer`` on the same edge); collapsing to one Static + one
internal grid sidesteps the layout fight entirely while keeping the
``mode·model·cost  /  chord chips  /  cache·worked·ctx`` layout the
user designed off the Rust footer. Middle chord hints omit ``⇧⇥ mode``
and ``⌃O models`` (shortcuts still work); only ``⌃P`` / ``⌃R`` remain.

Legacy parity (phase-E tests): the ``_status``, ``_model``, ``_mode``,
``_tokens`` attributes plus the legacy setters
(``set_status`` / ``set_model`` / ``set_mode`` / ``set_tokens``)
remain. ``set_cost`` / ``set_currency`` are the new
hooks the engine drives off ``TurnCompleteEvent``.
"""

import time

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from deepseek_tui.client.pricing import CostCurrency, format_cost_amount


class StatusBar(Static):
    """Single-row bottom status footer with three clusters."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    """

    _MIDDLE_CHORDS: tuple[tuple[str, str], ...] = (
        ("⌃P", "files"),
        ("⌃R", "sessions"),
    )

    _SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        super().__init__("")
        self._status: str = "ready"
        self._model: str = ""
        self._mode: str = ""
        self._tokens: int = 0
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._cost_usd: float = 0.0
        self._cost_cny: float = 0.0
        self._currency: CostCurrency = CostCurrency.USD
        self._spinning: bool = False
        self._spin_phase: str = ""
        self._spin_frame: int = 0
        self._spin_timer = None

    def on_mount(self) -> None:
        self._refresh()

    # --- legacy setters (phase-E parity) -----------------------------

    def set_status(self, text: str) -> None:
        self._status = text
        self._refresh()

    def set_model(self, model: str) -> None:
        self._model = model
        self._refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._refresh()

    def set_tokens(self, tokens: int) -> None:
        self._tokens = tokens
        self._refresh()

    def set_started(self, ts: float | None = None) -> None:
        self._started_at = ts if ts is not None else time.monotonic()
        self._finished_at = None
        self._start_spinner("thinking")
        self._refresh()

    def set_finished(self) -> None:
        if self._started_at is not None and self._finished_at is None:
            self._finished_at = time.monotonic()
        self._stop_spinner()
        self._refresh()

    def set_phase(self, phase: str) -> None:
        """Update the spinner phase label (e.g. tool name)."""
        if self._spinning:
            self._spin_phase = phase
            self._refresh()

    def _start_spinner(self, phase: str = "") -> None:
        self._spinning = True
        self._spin_phase = phase
        self._spin_frame = 0
        if self._spin_timer is None:
            self._spin_timer = self.set_interval(1 / 12, self._tick_spinner)

    def _stop_spinner(self) -> None:
        self._spinning = False
        self._spin_phase = ""
        if self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None

    def _tick_spinner(self) -> None:
        self._spin_frame = (self._spin_frame + 1) % len(self._SPINNER_FRAMES)
        self._refresh()

    # --- new setters -------------------------------------------------

    def set_cost(self, usd: float, cny: float = 0.0) -> None:
        self._cost_usd = max(0.0, usd)
        self._cost_cny = max(0.0, cny)
        self._refresh()

    def set_currency(self, currency: CostCurrency) -> None:
        self._currency = currency
        self._refresh()

    # --- cluster builders --------------------------------------------

    def _left_markup(self) -> Text:
        parts: list[str] = []
        if self._spinning:
            frame = self._SPINNER_FRAMES[self._spin_frame]
            label = self._spin_phase or "working"
            parts.append(f"[bold bright_cyan]{frame}[/] [bright_cyan]{label}[/]")
        if self._mode:
            parts.append(f"[bright_cyan]{self._mode}[/]")
        if self._model:
            parts.append(f"[bold bright_white]{self._model}[/]")
        cost_chip = self._cost_chip()
        if cost_chip:
            parts.append(cost_chip)
        if not self._spinning and self._status and self._status != "ready":
            parts.append(f"[dim bright_white]{self._status}[/]")
        if not parts:
            return Text("")
        return Text.from_markup("  [dim bright_black]·[/]  ".join(parts))

    def _cost_chip(self) -> str:
        amount = self._cost_usd if self._currency is CostCurrency.USD else self._cost_cny
        if amount <= 0.0:
            return ""
        return f"[dim]{format_cost_amount(amount, self._currency)}[/]"

    def _mid_markup(self) -> Text:
        chips = [f"[b bright_cyan]{key}[/] [dim bright_white]{label}[/]" for key, label in self._MIDDLE_CHORDS]
        return Text.from_markup("[dim bright_black]  ·  [/]".join(chips))

    def _right_markup(self) -> Text:
        parts: list[Text] = []
        if self._started_at is not None:
            end = (
                self._finished_at
                if self._finished_at is not None
                else time.monotonic()
            )
            secs = max(0.0, end - self._started_at)
            if secs >= 1.0:
                parts.append(Text(f"worked {secs:.0f}s", style="dim bright_white"))
        if self._tokens > 0:
            label = (
                f"{self._tokens / 1000:.1f}k ctx"
                if self._tokens >= 1000
                else f"{self._tokens} ctx"
            )
            parts.append(Text(label, style="dim bright_white"))
        if not parts:
            return Text("")
        out = Text()
        for i, p in enumerate(parts):
            if i > 0:
                out.append("  ·  ", style="dim bright_black")
            out.append_text(p)
        return out


    def _refresh(self) -> None:
        # Three columns: left auto-wide, middle expanding (chord chips
        # centered), right auto-wide. Rich's Table.grid handles widths
        # internally — no Textual dock fights, no missing rows.
        grid = Table.grid(expand=True, padding=(0, 2))
        grid.add_column(justify="left", no_wrap=True)
        grid.add_column(justify="center", ratio=1, no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_row(self._left_markup(), self._mid_markup(), self._right_markup())
        try:
            self.update(grid)
        except Exception:
            pass


# ======================================================================
# From frame_rate_limiter.py
# ======================================================================

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


# ======================================================================
# From osc8.py
# ======================================================================

"""OSC 8 hyperlink emission and stripping.

Mirrors ``crates/tui/src/tui/osc8.rs`` (165 LOC).

Modern terminals (iTerm2, Terminal.app 13+, Ghostty, Kitty, WezTerm,
Alacritty, recent gnome-terminal/konsole) make a substring clickable when
it is wrapped in::

    \\x1b]8;;TARGET\\x1b\\\\LABEL\\x1b]8;;\\x1b\\\\

Terminals that don't understand the sequence simply render the visible
``LABEL`` and ignore the escape. So emitting OSC 8 is a strict UX upgrade
for supporting terminals and a no-op for the rest.

The clipboard / selection extraction path must strip the codes before
handing text to the user — that's what :func:`strip_into` is for.
"""


OSC8_PREFIX = "\x1b]8;;"
OSC8_TERMINATOR = "\x1b\\"

_enabled: bool = True


def set_enabled(enabled: bool) -> None:
    """Set the process-wide OSC 8 enable flag."""
    global _enabled
    _enabled = enabled


def enabled() -> bool:
    """Whether OSC 8 hyperlink emission is currently enabled."""
    return _enabled


def wrap_link(target: str, label: str) -> str:
    """Wrap *label* so it links to *target* in OSC 8-aware terminals.

    Mirrors Rust ``wrap_link`` (osc8.rs:47).
    Does not check :func:`enabled` — callers wanting the runtime gate
    should branch on it before calling.
    """
    return f"{OSC8_PREFIX}{target}{OSC8_TERMINATOR}{label}{OSC8_PREFIX}{OSC8_TERMINATOR}"


def strip_into(s: str, out: list[str]) -> None:
    """Append *s* to *out* with OSC 8 escape sequences removed.

    Mirrors Rust ``strip_into`` (osc8.rs:62).
    Other escapes (color, style) pass through untouched. Handles both the
    standard ``ESC \\`` and lone ``BEL`` terminators.
    """
    data = s
    n = len(data)
    i = 0
    while i < n:
        if (
            i + 4 <= n
            and data[i] == "\x1b"
            and data[i + 1] == "]"
            and data[i + 2] == "8"
            and data[i + 3] == ";"
        ):
            j = i + 4
            while j < n:
                if data[j] == "\x07":
                    j += 1
                    break
                if data[j] == "\x1b" and j + 1 < n and data[j + 1] == "\\":
                    j += 2
                    break
                j += 1
            i = j
            continue
        out.append(data[i])
        i += 1


def strip(s: str) -> str:
    """Convenience wrapper around :func:`strip_into`."""
    parts: list[str] = []
    strip_into(s, parts)
    return "".join(parts)
