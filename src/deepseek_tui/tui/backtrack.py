"""Esc-Esc backtrack state machine.

Mirrors ``crates/tui/src/tui/backtrack.rs`` (386 LOC).

Lets the user rewind the active conversation to a previous user
message. The chord is intentionally two-step so a single stray ``Esc``
after a popup close cannot accidentally rewind a turn:

1. **First Esc** (no popup, no streaming, nothing to clear) — moves
   ``Inactive`` → ``Primed``. The composer surfaces a transient hint
   ("Press Esc again to backtrack").
2. **Second Esc** — moves ``Primed`` → ``Selecting``. The live-transcript
   overlay opens with the most recent user message highlighted.
   Left/Right step through prior user messages.
3. **Enter** — commits the selection: yields the chosen ``selected_idx``
   (a depth-from-tail offset, where ``0`` = newest user turn). Resets the
   machine to ``Inactive``.

The state machine knows nothing about the rest of the app — it stores
only the small bookkeeping required to pick the right user turn. UI
routing (popup detection, streaming guard, fork side effects) lives in
``DeepSeekTUI``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class BacktrackPhase(str, enum.Enum):
    """Mirror Rust ``BacktrackPhase`` (backtrack.rs:25)."""

    INACTIVE = "inactive"
    PRIMED = "primed"
    SELECTING = "selecting"


class Direction(str, enum.Enum):
    """Mirror Rust ``Direction`` (backtrack.rs:42)."""

    LEFT = "left"
    RIGHT = "right"


class EscEffect(str, enum.Enum):
    """What the caller should do in response to a single ``Esc``.

    Mirror Rust ``EscEffect`` (backtrack.rs:51).
    """

    NONE = "none"
    PRIME = "prime"
    CANCEL = "cancel"
    OPEN_OVERLAY = "open_overlay"


@dataclass(slots=True)
class BacktrackState:
    """Mirror Rust ``BacktrackState`` (backtrack.rs:72)."""

    phase: BacktrackPhase = BacktrackPhase.INACTIVE
    selected_idx: int = 0
    total: int = 0

    def is_active(self) -> bool:
        """``True`` whenever the user has armed or opened backtrack."""
        return self.phase != BacktrackPhase.INACTIVE

    def is_selecting(self) -> bool:
        """``True`` only when the overlay is open."""
        return self.phase == BacktrackPhase.SELECTING

    def get_selected_idx(self) -> int | None:
        """Depth-from-tail offset, if any."""
        if self.phase == BacktrackPhase.SELECTING:
            return self.selected_idx
        return None

    def handle_esc(self, total_user_messages: int) -> EscEffect:
        """Process an Esc press.

        Mirror Rust ``handle_esc`` (backtrack.rs:119).
        """
        if self.phase == BacktrackPhase.INACTIVE:
            if total_user_messages == 0:
                return EscEffect.NONE
            self.phase = BacktrackPhase.PRIMED
            return EscEffect.PRIME
        if self.phase == BacktrackPhase.PRIMED:
            if total_user_messages == 0:
                self.phase = BacktrackPhase.INACTIVE
                return EscEffect.CANCEL
            self.phase = BacktrackPhase.SELECTING
            self.selected_idx = 0
            self.total = total_user_messages
            return EscEffect.OPEN_OVERLAY
        # Selecting: defensive cancel
        self.phase = BacktrackPhase.INACTIVE
        self.selected_idx = 0
        self.total = 0
        return EscEffect.CANCEL

    def step(self, direction: Direction) -> None:
        """Step the selection while in ``Selecting``.

        Mirror Rust ``step`` (backtrack.rs:153).
        ``LEFT`` walks backward in time (older); ``RIGHT`` walks forward.
        Bounds-checked: ``selected_idx`` is clamped to ``[0, total - 1]``.
        """
        if self.phase != BacktrackPhase.SELECTING or self.total == 0:
            return
        last = self.total - 1
        if direction == Direction.LEFT:
            self.selected_idx = min(self.selected_idx + 1, last)
        else:
            self.selected_idx = max(self.selected_idx - 1, 0)

    def confirm(self) -> int | None:
        """Commit the current selection.

        Mirror Rust ``confirm`` (backtrack.rs:178). Returns the
        depth-from-tail offset (0 = newest user turn) and resets state;
        returns ``None`` if not currently selecting.
        """
        if self.phase != BacktrackPhase.SELECTING:
            return None
        idx = self.selected_idx
        self.phase = BacktrackPhase.INACTIVE
        self.selected_idx = 0
        self.total = 0
        return idx

    def reset(self) -> None:
        """Force the state machine back to ``Inactive``.

        Mirror Rust ``reset`` (backtrack.rs:192).
        """
        self.phase = BacktrackPhase.INACTIVE
        self.selected_idx = 0
        self.total = 0
