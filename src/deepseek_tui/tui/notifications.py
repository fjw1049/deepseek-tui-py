"""OSC 9 / BEL desktop notifications for long agent-turn completion.

Writes a terminal escape to the provided sink (or stdout for the public
API) when a turn takes longer than the configured threshold. Supports
tmux DCS passthrough so OSC 9 reaches the outer terminal even when
running inside a tmux session.
"""

from __future__ import annotations



import enum
import os
import sys
from typing import IO


class Method(str, enum.Enum):
    """Notification delivery method."""

    AUTO = "auto"
    OSC9 = "osc9"
    BEL = "bel"
    OFF = "off"

    @classmethod
    def from_str(cls, s: str) -> Method:
        """Parse from a configuration string (case-insensitive)."""
        v = s.strip().lower()
        if v in ("osc9", "osc-9"):
            return cls.OSC9
        if v == "bel":
            return cls.BEL
        if v in ("off", "disabled", "none"):
            return cls.OFF
        return cls.AUTO


def _resolve_method() -> Method:
    """Resolve AUTO to a concrete method by inspecting ``$TERM_PROGRAM``.

    Known OSC-9 capable: iTerm.app, Ghostty, WezTerm. Else BEL.
    """
    term_program = os.environ.get("TERM_PROGRAM", "")
    if term_program in ("iTerm.app", "Ghostty", "WezTerm"):
        return Method.OSC9
    return Method.BEL


def _build_escape(method: Method, in_tmux: bool, msg: str) -> bytes:
    """Build the raw escape bytes."""
    if method == Method.BEL:
        return b"\x07"
    if method == Method.OSC9:
        inner = f"\x1b]9;{msg}\x07"
        if in_tmux:
            escaped_inner = inner.replace("\x1b", "\x1b\x1b")
            return f"\x1bPtmux;{escaped_inner}\x1b\\".encode()
        return inner.encode()
    return b""


def notify_done_to(
    method: Method,
    in_tmux: bool,
    msg: str,
    threshold_secs: float,
    elapsed_secs: float,
    sink: IO[bytes],
) -> None:
    """Emit a turn-complete notification to *sink* if the threshold is met."""
    if elapsed_secs < threshold_secs:
        return
    effective = method
    if effective == Method.OFF:
        return
    if effective == Method.AUTO:
        effective = _resolve_method()
    payload = _build_escape(effective, in_tmux, msg)
    if not payload:
        return
    try:
        sink.write(payload)
        sink.flush()
    except (OSError, ValueError):
        pass


def notify_done(
    method: Method,
    in_tmux: bool,
    msg: str,
    threshold_secs: float,
    elapsed_secs: float,
) -> None:
    """Emit a turn-complete notification to stdout."""
    notify_done_to(method, in_tmux, msg, threshold_secs, elapsed_secs, sys.stdout.buffer)


def humanize_duration(seconds: float) -> str:
    """Return a compact human-readable duration string.

    Examples: ``"45s"``, ``"1m"``, ``"1m 12s"``, ``"1h"``, ``"3h 12m"``,
    ``"1d"``, ``"2d 5h"``, ``"1w"``, ``"3w 2d"``.
    """
    total = int(seconds)
    if total <= 0:
        return "0s"

    minute = 60
    hour = 60 * minute
    day = 24 * hour
    week = 7 * day

    if total >= week:
        w = total // week
        days = (total % week) // day
        return f"{w}w" if days == 0 else f"{w}w {days}d"
    if total >= day:
        days = total // day
        h = (total % day) // hour
        return f"{days}d" if h == 0 else f"{days}d {h}h"
    if total >= hour:
        h = total // hour
        m = (total % hour) // minute
        return f"{h}h" if m == 0 else f"{h}h {m}m"
    if total >= minute:
        m = total // minute
        s = total % minute
        return f"{m}m" if s == 0 else f"{m}m {s}s"
    return f"{total}s"
