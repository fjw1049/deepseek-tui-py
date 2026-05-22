"""Sub-agent activity cards (delegate + fanout).

Mirrors ``crates/tui/src/tui/widgets/agent_card.rs`` (671 LOC).

Two cards consume :class:`MailboxMessage` envelopes and surface a live
status line in the transcript:

- :class:`DelegateCard` — single ``agent_spawn`` invocation. Header with
  status glyph + role + agent id, plus the last
  :data:`DELEGATE_MAX_ACTIONS` action lines. Older entries are dropped
  from the head and an ellipsis row signals truncation.
- :class:`FanoutCard` — multi-child dispatch (``rlm`` etc.). Dot-grid
  with one glyph per worker plus an aggregate counts line.

The state-machine half of each card is plain Python so unit tests can
drive it without a Textual runtime. The :class:`AgentCardWidget` is a
thin :class:`textual.widgets.Static` adapter that renders a card's
current state using Rich markup.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from textual.widgets import Static

from deepseek_tui.tools.subagent.mailbox import MailboxMessage, MailboxMessageKind

DELEGATE_MAX_ACTIONS: int = 3


class AgentLifecycle(str, enum.Enum):
    """Mirror Rust ``AgentLifecycle`` (agent_card.rs:30)."""

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
    """Single ``agent_spawn`` invocation card.

    Mirror Rust ``DelegateCard`` (agent_card.rs:69).
    """

    agent_id: str
    agent_type: str
    status: AgentLifecycle = AgentLifecycle.PENDING
    summary: str | None = None
    actions: list[str] = field(default_factory=list)
    truncated: bool = False

    def push_action(self, action: str) -> None:
        """Append ``action``; drop the head past :data:`DELEGATE_MAX_ACTIONS`.

        Mirror Rust ``push_action`` (agent_card.rs:91).
        """
        self.actions.append(action)
        if len(self.actions) > DELEGATE_MAX_ACTIONS:
            self.actions.pop(0)
            self.truncated = True

    def render_lines(self) -> list[str]:
        """Render the card as a list of Rich-markup lines.

        Mirror Rust ``render_lines`` (agent_card.rs:102). Returns one
        string per visual line; the caller joins with ``\\n``.
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
# Fanout card
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WorkerSlot:
    """Mirror Rust ``WorkerSlot`` (agent_card.rs:157)."""

    worker_id: str
    agent_id: str
    status: AgentLifecycle

    @classmethod
    def new(cls, worker_id: str, status: AgentLifecycle) -> WorkerSlot:
        return cls(worker_id=worker_id, agent_id=worker_id, status=status)


_DOT_GLYPH = {
    AgentLifecycle.COMPLETED: "●",
    AgentLifecycle.RUNNING: "◐",
    AgentLifecycle.FAILED: "×",
    AgentLifecycle.CANCELLED: "⊘",
    AgentLifecycle.PENDING: "○",
}


@dataclass(slots=True)
class FanoutCard:
    """Multi-child dispatch card (one slot per worker).

    Mirror Rust ``FanoutCard`` (agent_card.rs:186).
    """

    kind: str
    workers: list[WorkerSlot] = field(default_factory=list)

    def with_workers(self, ids: list[str]) -> FanoutCard:
        for worker_id in ids:
            self.workers.append(WorkerSlot.new(worker_id, AgentLifecycle.PENDING))
        return self

    def upsert_worker(self, agent_id: str, status: AgentLifecycle) -> None:
        """Mirror Rust ``upsert_worker`` (agent_card.rs:215)."""
        for slot in self.workers:
            if slot.agent_id == agent_id or slot.worker_id == agent_id:
                slot.agent_id = agent_id
                slot.status = status
                return
        self.workers.append(WorkerSlot.new(agent_id, status))

    def claim_pending_worker(self, agent_id: str, status: AgentLifecycle) -> None:
        """Bind a real agent id to the first pending placeholder slot.

        Mirror Rust ``claim_pending_worker`` (agent_card.rs:232). Keeps
        the dot count stable when the engine pre-seeds workers and
        children attach later.
        """
        for slot in self.workers:
            if slot.agent_id == agent_id:
                slot.status = status
                return
        for slot in self.workers:
            if slot.status == AgentLifecycle.PENDING:
                slot.agent_id = agent_id
                slot.status = status
                return
        self.upsert_worker(agent_id, status)

    def counts(self) -> tuple[int, int, int, int]:
        done = running = failed = pending = 0
        for slot in self.workers:
            if slot.status == AgentLifecycle.COMPLETED:
                done += 1
            elif slot.status == AgentLifecycle.RUNNING:
                running += 1
            elif slot.status in (AgentLifecycle.FAILED, AgentLifecycle.CANCELLED):
                failed += 1
            else:
                pending += 1
        return done, running, failed, pending

    def dot_grid(self) -> str:
        return "".join(_DOT_GLYPH[slot.status] for slot in self.workers)

    def aggregate_status(self) -> AgentLifecycle:
        done, running, failed, pending = self.counts()
        if running > 0 or pending > 0:
            return AgentLifecycle.RUNNING
        if failed > 0 and done == 0:
            return AgentLifecycle.FAILED
        if done > 0:
            return AgentLifecycle.COMPLETED
        return AgentLifecycle.PENDING

    def render_lines(self) -> list[str]:
        title = f"{self.kind} ({len(self.workers)} workers)"
        lines: list[str] = [
            _card_header("fanout", self.aggregate_status(), self.kind, title),
            f"  [bold cyan]{self.dot_grid()}[/]",
        ]
        done, running, failed, pending = self.counts()
        lines.append(
            f"  [dim]{done} done · {running} running · "
            f"{failed} failed · {pending} pending[/]"
        )
        return lines

    def render_text(self) -> str:
        return "\n".join(self.render_lines())


# ---------------------------------------------------------------------------
# Mailbox dispatch
# ---------------------------------------------------------------------------


def apply_to_delegate(card: DelegateCard, msg: MailboxMessage) -> bool:
    """Apply a mailbox envelope to ``card``.

    Mirror Rust ``apply_to_delegate`` (agent_card.rs:382). Returns True
    if the card state changed.
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


def apply_to_fanout(card: FanoutCard, msg: MailboxMessage) -> bool:
    """Mirror Rust ``apply_to_fanout`` (agent_card.rs:438)."""
    agent_id = msg.agent_id
    kind = msg.kind
    if kind == MailboxMessageKind.STARTED:
        card.claim_pending_worker(agent_id, AgentLifecycle.RUNNING)
    elif kind in (
        MailboxMessageKind.PROGRESS,
        MailboxMessageKind.TOOL_CALL_STARTED,
    ):
        card.claim_pending_worker(agent_id, AgentLifecycle.RUNNING)
    elif kind == MailboxMessageKind.TOOL_CALL_COMPLETED:
        return True
    elif kind == MailboxMessageKind.COMPLETED:
        card.upsert_worker(agent_id, AgentLifecycle.COMPLETED)
    elif kind == MailboxMessageKind.FAILED:
        card.upsert_worker(agent_id, AgentLifecycle.FAILED)
    elif kind == MailboxMessageKind.CANCELLED:
        card.upsert_worker(agent_id, AgentLifecycle.CANCELLED)
    elif kind == MailboxMessageKind.CHILD_SPAWNED:
        # ``agent_id`` here carries the *child* id (see Mailbox.child_spawned).
        card.upsert_worker(agent_id, AgentLifecycle.PENDING)
    elif kind == MailboxMessageKind.TOKEN_USAGE:
        return True
    return True


# ---------------------------------------------------------------------------
# Helpers + Textual widget
# ---------------------------------------------------------------------------


_FAMILY_GLYPH = {"delegate": "↳", "fanout": "⫶", "rlm": "Σ"}


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
    """Textual adapter that renders a :class:`DelegateCard` or :class:`FanoutCard`.

    The widget owns no card state — pass the current card on construction
    and call :meth:`update_card` whenever the state changes.
    """

    DEFAULT_CSS = "AgentCardWidget { margin: 0 0 1 0; }"

    def __init__(self, card: DelegateCard | FanoutCard) -> None:
        super().__init__("")
        self._card = card
        self.update(card.render_text())

    def update_card(self, card: DelegateCard | FanoutCard) -> None:
        self._card = card
        self.update(card.render_text())
