"""Plan prompt and backtrack UI.
"""

from __future__ import annotations



# Plan-mode confirmation prompt.
#
# After a plan is generated in plan mode, the user must pick one of four
# options:
#
# 1. Accept plan (Agent) — start implementation with approvals
# 2. Accept plan (YOLO) — start implementation, auto-approve
# 3. Revise plan — ask follow-ups or request changes
# 4. Exit plan mode — return to Agent mode without implementation
#
# This module provides the data + selection state machine plus a Textual
# ``ModalScreen`` for interactive picking. The unit tests cover the edge
# cases (digit shortcuts, letter shortcuts, up/down navigation,
# enter/escape).
#
import enum
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static


class PlanOutcome(str, enum.Enum):
    """Outcome of the plan prompt."""

    ACCEPT_AGENT = "accept_agent"
    ACCEPT_YOLO = "accept_yolo"
    REVISE = "revise"
    EXIT_PLAN = "exit_plan"
    DISMISSED = "dismissed"


PLAN_OPTIONS: list[tuple[PlanOutcome, str, str]] = [
    (PlanOutcome.ACCEPT_AGENT, "Accept plan (Agent)",
     "Start implementation in Agent mode with approvals"),
    (PlanOutcome.ACCEPT_YOLO, "Accept plan (YOLO)",
     "Start implementation in YOLO mode (auto-approve)"),
    (PlanOutcome.REVISE, "Revise plan",
     "Ask follow-ups or request plan changes"),
    (PlanOutcome.EXIT_PLAN, "Exit Plan mode",
     "Return to Agent mode without implementation"),
]


@dataclass(slots=True)
class PlanPromptState:
    """Pure state machine for plan prompt selection.

    Decoupled from the Textual screen so unit tests don't need a UI runtime.
    """

    selected: int = 0

    def max_index(self) -> int:
        return len(PLAN_OPTIONS) - 1

    def move_up(self) -> None:
        self.selected = max(0, self.selected - 1)

    def move_down(self) -> None:
        self.selected = min(self.max_index(), self.selected + 1)

    def submit(self) -> PlanOutcome:
        return PLAN_OPTIONS[self.selected][0]

    def submit_number(self, number: int) -> PlanOutcome | None:
        """Quick-pick by 1-4. Returns None if out of range."""
        if 1 <= number <= len(PLAN_OPTIONS):
            self.selected = number - 1
            return self.submit()
        return None

    def submit_letter(self, letter: str) -> PlanOutcome | None:
        """Quick-pick by letter (a/y/r/q/e)."""
        ch = letter.lower()
        if ch == "a":
            self.selected = 0
            return self.submit()
        if ch == "y":
            self.selected = 1
            return self.submit()
        if ch == "r":
            self.selected = 2
            return self.submit()
        if ch in ("q", "e"):
            self.selected = 3
            return self.submit()
        return None


class PlanPromptScreen(ModalScreen[PlanOutcome]):
    """Modal screen for plan confirmation.

    Pop with :meth:`App.push_screen` and await the result. The handler
    on the resolution side picks the action based on the returned
    :class:`PlanOutcome`.
    """

    BINDINGS = [
        Binding("up,k", "move_up", show=False),
        Binding("down,j", "move_down", show=False),
        Binding("1", "pick(1)", show=False),
        Binding("2", "pick(2)", show=False),
        Binding("3", "pick(3)", show=False),
        Binding("4", "pick(4)", show=False),
        Binding("a", "letter('a')", show=False),
        Binding("y", "letter('y')", show=False),
        Binding("r", "letter('r')", show=False),
        Binding("q,e", "letter('q')", show=False),
        Binding("enter", "confirm", show=False),
        Binding("escape", "dismiss_modal", show=False),
    ]

    DEFAULT_CSS = """
    PlanPromptScreen {
        align: center middle;
    }
    #plan-modal {
        width: 70;
        height: 18;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.state = PlanPromptState()

    def compose(self) -> ComposeResult:
        yield Static(id="plan-modal")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        body = self.query_one("#plan-modal", Static)
        lines: list[str] = []
        lines.append("[bold cyan]Plan Confirmation[/]")
        lines.append("[bold]Choose what should happen after this plan.[/]")
        lines.append("")
        for idx, (_, label, description) in enumerate(PLAN_OPTIONS):
            number = idx + 1
            if idx == self.state.selected:
                lines.append(f"[bold reverse]> {number}) {label}[/]")
                lines.append(f"[bold reverse]    {description}[/]")
            else:
                lines.append(f"  {number}) {label}")
                lines.append(f"    [dim]{description}[/]")
        lines.append("")
        lines.append(
            "[bold]1-4[/] / [bold]a/y/r/q[/] quick pick   "
            "[bold]Up/Down[/] move   "
            "[bold]Enter[/] confirm   "
            "[bold]Esc[/] close"
        )
        body.update("\n".join(lines))

    def action_move_up(self) -> None:
        self.state.move_up()
        self._refresh()

    def action_move_down(self) -> None:
        self.state.move_down()
        self._refresh()

    def action_pick(self, number: int) -> None:
        outcome = self.state.submit_number(int(number))
        if outcome is not None:
            self.dismiss(outcome)

    def action_letter(self, letter: str) -> None:
        outcome = self.state.submit_letter(letter)
        if outcome is not None:
            self.dismiss(outcome)

    def action_confirm(self) -> None:
        self.dismiss(self.state.submit())

    def action_dismiss_modal(self) -> None:
        self.dismiss(PlanOutcome.DISMISSED)


# Esc-Esc backtrack state machine.
#
# Lets the user rewind the active conversation to a previous user
# message. The chord is intentionally two-step so a single stray ``Esc``
# after a popup close cannot accidentally rewind a turn:
#
# 1. **First Esc** (no popup, no streaming, nothing to clear) — moves
#    ``Inactive`` → ``Primed``. The composer surfaces a transient hint
#    ("Press Esc again to backtrack").
# 2. **Second Esc** — moves ``Primed`` → ``Selecting``. The live-transcript
#    overlay opens with the most recent user message highlighted.
#    Left/Right step through prior user messages.
# 3. **Enter** — commits the selection: yields the chosen ``selected_idx``
#    (a depth-from-tail offset, where ``0`` = newest user turn). Resets the
#    machine to ``Inactive``.
#
# The state machine knows nothing about the rest of the app — it stores
# only the small bookkeeping required to pick the right user turn. UI
# routing (popup detection, streaming guard, fork side effects) lives in
# ``DeepSeekTUI``.
#


class BacktrackPhase(str, enum.Enum):
    """Backtrack phase state."""

    INACTIVE = "inactive"
    PRIMED = "primed"
    SELECTING = "selecting"


class Direction(str, enum.Enum):
    """Selection navigation direction."""

    LEFT = "left"
    RIGHT = "right"


class EscEffect(str, enum.Enum):
    """What the caller should do in response to a single ``Esc``."""

    NONE = "none"
    PRIME = "prime"
    CANCEL = "cancel"
    OPEN_OVERLAY = "open_overlay"


@dataclass(slots=True)
class BacktrackState:
    """Backtrack selection state machine."""

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
        """Process an Esc press."""
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

        Returns the depth-from-tail offset (0 = newest user turn) and resets
        state; returns ``None`` if not currently selecting.
        """
        if self.phase != BacktrackPhase.SELECTING:
            return None
        idx = self.selected_idx
        self.phase = BacktrackPhase.INACTIVE
        self.selected_idx = 0
        self.total = 0
        return idx

    def reset(self) -> None:
        """Force the state machine back to ``Inactive``."""
        self.phase = BacktrackPhase.INACTIVE
        self.selected_idx = 0
        self.total = 0
