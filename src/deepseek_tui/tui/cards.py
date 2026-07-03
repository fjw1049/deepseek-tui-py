"""Agent card and pager widgets.

Sub-agent activity card:

- :class:`DelegateCard` — single ``agent_spawn`` invocation. Header with
  status glyph + role + agent id, plus the last
  :data:`DELEGATE_MAX_ACTIONS` action lines. Older entries are dropped
  from the head and an ellipsis row signals truncation.

The state-machine half of the card is plain Python so unit tests can
drive it without a Textual runtime. The :class:`AgentCardWidget` is a
thin :class:`textual.widgets.Static` adapter that renders a card's
current state using Rich markup.

Long-output pager overlay:
:class:`PagerState` (pure key/scroll state machine) + :class:`PagerScreen`
(Textual modal adapter).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from deepseek_tui.tools.subagent import MailboxMessage, MailboxMessageKind

DELEGATE_MAX_ACTIONS: int = 3


class AgentLifecycle(str, enum.Enum):
    """Lifecycle state of a sub-agent."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        return self in (
            AgentLifecycle.COMPLETED,
            AgentLifecycle.FAILED,
            AgentLifecycle.CANCELLED,
        )

    def label(self) -> str:
        return {
            AgentLifecycle.PENDING: "pending",
            AgentLifecycle.RUNNING: "running",
            AgentLifecycle.COMPLETED: "done",
            AgentLifecycle.FAILED: "failed",
            AgentLifecycle.CANCELLED: "cancelled",
        }[self]

    def color(self) -> str:
        """Rich color name for header / summary spans."""
        return {
            AgentLifecycle.PENDING: "dim",
            AgentLifecycle.RUNNING: "yellow",
            AgentLifecycle.COMPLETED: "green",
            AgentLifecycle.FAILED: "red",
            AgentLifecycle.CANCELLED: "dim",
        }[self]


# ---------------------------------------------------------------------------
# Delegate card
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DelegateCard:
    """Single ``agent_spawn`` invocation card."""

    agent_id: str
    agent_type: str
    status: AgentLifecycle = AgentLifecycle.PENDING
    summary: str | None = None
    actions: list[str] = field(default_factory=list)
    truncated: bool = False

    def push_action(self, action: str) -> None:
        """Append ``action``; drop the head past :data:`DELEGATE_MAX_ACTIONS`."""
        self.actions.append(action)
        if len(self.actions) > DELEGATE_MAX_ACTIONS:
            self.actions.pop(0)
            self.truncated = True

    def render_lines(self) -> list[str]:
        """Render the card as a list of Rich-markup lines.

        Returns one string per visual line; the caller joins with ``\\n``.
        """
        lines: list[str] = [
            _card_header(
                "delegate",
                self.status,
                self.agent_type,
                _display_agent_id(self.agent_id),
            )
        ]
        if self.truncated:
            lines.append("  [dim]…[/]")
        for action in self.actions:
            lines.append(f"  [dim]│[/] {_truncate(action, 200)}")
        if self.status.is_terminal() and self.summary:
            display = _summary_for_display(self.summary) or self.summary
            lines.append(
                f"  [dim]╰[/] [{self.status.color()}]"
                f"{_truncate(display, 200)}[/]"
            )
        return lines

    def render_text(self) -> str:
        return "\n".join(self.render_lines())


# ---------------------------------------------------------------------------
# Mailbox dispatch
# ---------------------------------------------------------------------------


def apply_to_delegate(card: DelegateCard, msg: MailboxMessage) -> bool:
    """Apply a mailbox envelope to ``card``.

    Returns True if the card state changed.
    """
    if msg.agent_id != card.agent_id:
        return False
    kind = msg.kind
    if kind == MailboxMessageKind.STARTED:
        card.status = AgentLifecycle.RUNNING
    elif kind == MailboxMessageKind.PROGRESS:
        card.status = AgentLifecycle.RUNNING
        if msg.status:
            card.push_action(msg.status)
    elif kind == MailboxMessageKind.TOOL_CALL_STARTED:
        card.push_action(f"[{msg.step}] {msg.tool_name} started")
    elif kind == MailboxMessageKind.TOOL_CALL_COMPLETED:
        outcome = "ok" if msg.ok else "failed"
        card.push_action(f"[{msg.step}] {msg.tool_name} {outcome}")
    elif kind == MailboxMessageKind.COMPLETED:
        card.status = AgentLifecycle.COMPLETED
        card.summary = msg.summary
    elif kind == MailboxMessageKind.FAILED:
        card.status = AgentLifecycle.FAILED
        card.summary = msg.error
    elif kind == MailboxMessageKind.CANCELLED:
        card.status = AgentLifecycle.CANCELLED
    elif kind == MailboxMessageKind.CHILD_SPAWNED:
        return False
    elif kind == MailboxMessageKind.TOKEN_USAGE:
        return False
    return True


# ---------------------------------------------------------------------------
# Helpers + Textual widget
# ---------------------------------------------------------------------------


_FAMILY_GLYPH = {"delegate": "↳", "fanout": "⫶"}


def _card_header(family: str, status: AgentLifecycle, role: str, detail: str) -> str:
    glyph = _FAMILY_GLYPH.get(family, "•")
    color = status.color()
    return (
        f"[{color} bold]{glyph}  {family}[/] "
        f"[white]{role}[/] "
        f"[{color}][{status.label()}][/] "
        f"[dim]{detail}[/]"
    )


def _truncate(text: str, max_len: int) -> str:
    trimmed = text.strip()
    if len(trimmed) <= max_len:
        return trimmed
    return trimmed[: max_len - 1] + "…"


def _summary_for_display(raw: str | None) -> str | None:
    """Show the sub-agent conclusion, not the full structured report."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if "### SUMMARY" in text:
        section = text.split("### SUMMARY", 1)[1]
        lines: list[str] = []
        for line in section.splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                break
            if stripped:
                lines.append(stripped)
        if lines:
            return _truncate(" ".join(lines), 200)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return _truncate(stripped, 200)
    return _truncate(text, 200)


def _display_agent_id(agent_id: str) -> str:
    return agent_id if len(agent_id) <= 12 else agent_id[:12]


class AgentCardWidget(Static):
    """Textual adapter that renders a :class:`DelegateCard`.

    The widget owns no card state — pass the current card on construction
    and call :meth:`update_card` whenever the state changes.
    """

    DEFAULT_CSS = "AgentCardWidget { margin: 0 0 1 0; }"

    def __init__(self, card: DelegateCard) -> None:
        super().__init__("")
        self._card = card
        self.update(card.render_text())

    def update_card(self, card: DelegateCard) -> None:
        self._card = card
        self.update(card.render_text())


# ---------------------------------------------------------------------------
# Long-output pager overlay.
#
# Vim-style key bindings:
#
# - ``j`` / Down       — scroll down one line
# - ``k`` / Up         — scroll up one line
# - ``g g`` / Home     — jump to top (the chord state lives on
#   :class:`PagerState.pending_g`)
# - ``G`` / End        — jump to bottom
# - ``Ctrl+D`` / ``Ctrl+U``  — half-page down / up
# - ``Ctrl+F`` / ``Ctrl+B`` / Space / Shift+Space / PageDown / PageUp
#   — full page down / up
# - ``/`` — start search; ``Enter`` commits, ``Esc`` cancels.
# - ``n`` / ``N`` — next / previous match.
# - ``q`` / ``Esc`` — close.
# ---------------------------------------------------------------------------


class PagerAction(str, enum.Enum):
    """What the host should do after :meth:`PagerState.handle_key`."""

    NONE = "none"
    CLOSE = "close"
    REDRAW = "redraw"


@dataclass(slots=True)
class PagerState:
    """Pure state machine for the pager."""

    title: str
    lines: list[str]
    scroll: int = 0
    search_input: str = ""
    search_matches: list[int] = field(default_factory=list)
    search_index: int = 0
    search_mode: bool = False
    pending_g: bool = False
    visible_height: int = 10

    def max_scroll(self) -> int:
        return max(0, len(self.lines) - 1)

    def page_height(self) -> int:
        return self.visible_height if self.visible_height > 0 else 10

    def half_page_height(self) -> int:
        # ceil(page / 2), at least 1.
        page = self.page_height()
        return max(1, -(-page // 2))

    # -- scroll primitives ---------------------------------------------

    def scroll_up(self, amount: int) -> None:
        self.scroll = max(0, self.scroll - max(0, amount))

    def scroll_down(self, amount: int) -> None:
        self.scroll = min(self.max_scroll(), self.scroll + max(0, amount))

    def scroll_to_top(self) -> None:
        self.scroll = 0

    def scroll_to_bottom(self) -> None:
        self.scroll = self.max_scroll()

    # -- search --------------------------------------------------------

    def start_search(self) -> None:
        self.search_mode = True
        self.search_input = ""
        self.search_matches = []
        self.search_index = 0

    def update_search_matches(self) -> None:
        query = self.search_input.strip().lower()
        if not query:
            self.search_matches = []
            self.search_index = 0
            return
        self.search_matches = [
            i for i, line in enumerate(self.lines) if query in line.lower()
        ]
        self.search_index = 0

    def jump_to_match(self) -> None:
        if 0 <= self.search_index < len(self.search_matches):
            self.scroll = self.search_matches[self.search_index]

    def next_match(self) -> None:
        if not self.search_matches:
            return
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self.jump_to_match()

    def prev_match(self) -> None:
        if not self.search_matches:
            return
        if self.search_index == 0:
            self.search_index = len(self.search_matches) - 1
        else:
            self.search_index -= 1
        self.jump_to_match()

    # -- key dispatch (host-agnostic) ----------------------------------

    def handle_key(self, key: str, *, ctrl: bool = False, shift: bool = False) -> PagerAction:
        """Apply a key press; returns whether the host should redraw / close.

        ``key`` follows Textual conventions: lowercase letters,
        ``escape``/``enter``/``space``, arrow / paging key names. Ctrl + Shift
        modifiers are explicit flags rather than embedded in the key string.
        """
        if self.search_mode:
            return self._handle_search_key(key)

        if ctrl and key in ("d",):
            self.scroll_down(self.half_page_height())
            self.pending_g = False
            return PagerAction.REDRAW
        if ctrl and key == "u":
            self.scroll_up(self.half_page_height())
            self.pending_g = False
            return PagerAction.REDRAW
        if ctrl and key == "f":
            self.scroll_down(self.page_height())
            self.pending_g = False
            return PagerAction.REDRAW
        if ctrl and key == "b":
            self.scroll_up(self.page_height())
            self.pending_g = False
            return PagerAction.REDRAW

        if key in ("escape", "q"):
            return PagerAction.CLOSE
        if key in ("up", "k"):
            self.scroll_up(1)
            self.pending_g = False
            return PagerAction.REDRAW
        if key in ("down", "j"):
            self.scroll_down(1)
            self.pending_g = False
            return PagerAction.REDRAW
        if key == "pageup" or (key == "space" and shift):
            self.scroll_up(self.page_height())
            self.pending_g = False
            return PagerAction.REDRAW
        if key in ("pagedown", "space"):
            self.scroll_down(self.page_height())
            self.pending_g = False
            return PagerAction.REDRAW
        if key == "home":
            self.scroll_to_top()
            self.pending_g = False
            return PagerAction.REDRAW
        if key == "end":
            self.scroll_to_bottom()
            self.pending_g = False
            return PagerAction.REDRAW
        if key == "g":
            if self.pending_g:
                self.scroll_to_top()
                self.pending_g = False
            else:
                self.pending_g = True
            return PagerAction.REDRAW
        if key == "G":
            self.scroll_to_bottom()
            self.pending_g = False
            return PagerAction.REDRAW
        if key == "/":
            self.start_search()
            self.pending_g = False
            return PagerAction.REDRAW
        if key == "n":
            self.next_match()
            self.pending_g = False
            return PagerAction.REDRAW
        if key == "N":
            self.prev_match()
            self.pending_g = False
            return PagerAction.REDRAW
        return PagerAction.NONE

    def _handle_search_key(self, key: str) -> PagerAction:
        if key == "enter":
            self.search_mode = False
            self.update_search_matches()
            self.jump_to_match()
            return PagerAction.REDRAW
        if key == "escape":
            self.search_mode = False
            self.search_input = ""
            self.search_matches = []
            self.search_index = 0
            return PagerAction.REDRAW
        if key == "backspace":
            self.search_input = self.search_input[:-1]
            return PagerAction.REDRAW
        if len(key) == 1 and key.isprintable():
            self.search_input += key
            return PagerAction.REDRAW
        return PagerAction.NONE

    # -- view helpers --------------------------------------------------

    def visible_lines(self) -> list[str]:
        end = min(len(self.lines), self.scroll + self.visible_height)
        return list(self.lines[self.scroll : end])

    def status_line(self) -> str:
        if self.search_mode:
            return f"/{self.search_input}"
        if self.search_matches:
            return (
                f"match {self.search_index + 1}/{len(self.search_matches)} "
                "(n/N navigate)"
            )
        if self.lines:
            pct = int(100 * (self.scroll / max(1, self.max_scroll())))
            return f"{pct}%"
        return ""


# ---------------------------------------------------------------------------
# Textual screen
# ---------------------------------------------------------------------------


_FOOTER_HINT = (
    " j/k scroll  Space/b page  Ctrl+D/U half  g/G top/bottom  / search  q quit "
)


class PagerScreen(ModalScreen[None]):
    """Modal pager overlay backed by :class:`PagerState`."""

    BINDINGS = [
        Binding("up,k", "key('up')", show=False),
        Binding("down,j", "key('down')", show=False),
        Binding("pageup", "key('pageup')", show=False),
        Binding("pagedown", "key('pagedown')", show=False),
        Binding("home", "key('home')", show=False),
        Binding("end", "key('end')", show=False),
        Binding("space", "key('space')", show=False),
        Binding("g", "key('g')", show=False),
        Binding("G", "key('G')", show=False),
        Binding("slash", "key('/')", show=False),
        Binding("n", "key('n')", show=False),
        Binding("N", "key('N')", show=False),
        Binding("q,escape", "key('q')", show=False),
        Binding("ctrl+d", "key_ctrl('d')", show=False),
        Binding("ctrl+u", "key_ctrl('u')", show=False),
        Binding("ctrl+f", "key_ctrl('f')", show=False),
        Binding("ctrl+b", "key_ctrl('b')", show=False),
    ]

    DEFAULT_CSS = """
    PagerScreen {
        align: center middle;
    }
    #pager-modal {
        width: 90%;
        height: 90%;
        border: round $accent;
        background: $surface;
        padding: 0 1;
    }
    #pager-body {
        height: 1fr;
    }
    #pager-search {
        height: auto;
        margin-top: 1;
        display: none;
    }
    #pager-search.visible {
        display: block;
    }
    #pager-status {
        height: 1;
        color: $accent;
    }
    #pager-footer {
        height: 1;
        color: $accent-darken-2;
    }
    """

    def __init__(self, title: str, lines: list[str]) -> None:
        super().__init__()
        self._state = PagerState(title=title, lines=list(lines))

    def compose(self) -> ComposeResult:
        with Vertical(id="pager-modal"):
            yield Label(f"[bold]{self._state.title}[/]", id="pager-title")
            yield Static("", id="pager-body")
            yield Input(placeholder="search…", id="pager-search")
            yield Label("", id="pager-status")
            yield Label(_FOOTER_HINT, id="pager-footer")

    def on_mount(self) -> None:
        self._refresh()

    def action_key(self, key: str) -> None:
        action = self._state.handle_key(key)
        if action == PagerAction.CLOSE:
            self.dismiss(None)
            return
        self._refresh()

    def action_key_ctrl(self, key: str) -> None:
        action = self._state.handle_key(key, ctrl=True)
        if action == PagerAction.CLOSE:
            self.dismiss(None)
            return
        self._refresh()

    def _refresh(self) -> None:
        body = self.query_one("#pager-body", Static)
        body.update("\n".join(self._state.visible_lines()))
        status = self.query_one("#pager-status", Label)
        status.update(self._state.status_line())
        search = self.query_one("#pager-search", Input)
        if self._state.search_mode:
            search.add_class("visible")
            search.value = self._state.search_input
            search.focus()
        else:
            search.remove_class("visible")
