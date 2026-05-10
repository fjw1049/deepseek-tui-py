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

from __future__ import annotations

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
