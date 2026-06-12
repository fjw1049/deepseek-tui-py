"""Conversation transcript widget — Rust-style glyph + markdown cells.

Stage 6 (TUI polish, 2026-05-11): retired the bare ``You: / Assistant: /
System:`` prefix labels and the escape-everything-as-plaintext
``_AssistantCell``. The transcript now mirrors the Rust catalog in
``crates/tui/src/tui/history.rs``:

- ``▎`` user glyph + escaped body (single Static line)
- ``●`` assistant header glyph + markdown body (Rich ``Group``)
- ``…`` thinking header + ``╎ `` rail per body line; collapses on
  finalize when ``show_thinking`` is enabled, dropped entirely when
  the user toggled it off
- structured notices (info / warning / error) replace the System
  catch-all that previously absorbed engine errors, mode-cycle hints,
  ESC chord priming, etc.
- thin ``─`` ``_TurnDivider`` mounted on ``finalize_message`` so
  successive turns get a clean break

External content (user text / thinking / tool result) still passes
through ``rich.markup.escape`` — the contract pinned by
``tests/parity/phase_e/test_markup_escape.py``.

The legacy ``Transcript._messages`` parallel list is preserved verbatim
(``[bold cyan]You:[/] …`` style strings) so the parity test in
``tests/parity/phase_e/test_tui_wiring.py`` keeps passing while the
visible rendering changes.
"""

from __future__ import annotations


import logging
import time
from typing import Literal

from rich.align import Align
from rich.console import Group as _Group
from rich.markdown import Markdown as RichMarkdown
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.containers import VerticalScroll
from textual.widgets import Static

from deepseek_tui.tui.status import FrameRateLimiter
from deepseek_tui.tui.tool_cell import ToolCell
from deepseek_tui.tools.subagent import MailboxMessage, MailboxMessageKind
from deepseek_tui.tui.sanitize import strip_subagent_sentinels

logger = logging.getLogger(__name__)

_USER_GLYPH = "▎"
_ASSISTANT_GLYPH = "●"
_REASONING_OPENER = "…"
_REASONING_RAIL = "╎"
_DETAIL_RAIL = "▏"
_CURSOR = "▌"

NoticeSeverity = Literal["info", "warning", "error"]


class _UserCell(Static):
    DEFAULT_CSS = "_UserCell { margin: 1 0 0 0; }"

    def __init__(self, text: str) -> None:
        super().__init__(f"[bold bright_cyan]{_USER_GLYPH}[/] {escape(text)}")


class _AssistantCell(Static):
    """Streaming assistant cell. Glyph header + markdown body.

    The body is rendered as Rich ``Markdown`` (with a monokai code
    theme) once any non-whitespace content arrives; before that, the
    cell shows just the glyph plus a ``▌`` cursor. The redraw rate is
    capped via :class:`FrameRateLimiter` so a flood of SSE chunks does
    not trigger a redraw per chunk.
    """

    DEFAULT_CSS = "_AssistantCell { margin: 1 0 0 0; }"

    def __init__(self) -> None:
        super().__init__("")
        self._buffer: str = ""
        self._finalized: bool = False
        self._limiter = FrameRateLimiter()
        self._refresh(force=True)

    def append(self, text: str) -> None:
        self._buffer += text
        if self._finalized:
            self._refresh(force=True)
            return
        now = time.monotonic()
        if self._limiter.time_until_next_draw(now) is None:
            self._limiter.mark_emitted(now)
            self._refresh(force=False)

    def finalize(self) -> None:
        self._finalized = True
        self._refresh(force=True)

    @property
    def content_text(self) -> str:
        return self._buffer

    def _refresh(self, force: bool) -> None:
        glyph_style = "bright_green" if self._finalized else "bold bright_green"
        glyph = Text(_ASSISTANT_GLYPH, style=glyph_style)
        if not self._buffer.strip():
            cursor_text = (
                Text("", style="dim")
                if self._finalized
                else Text(_CURSOR, style="bold bright_green blink")
            )
            self.update(_Group(glyph, cursor_text))
            return
        cursor_suffix = "" if self._finalized else f" {_CURSOR}"
        body_source = self._buffer + cursor_suffix
        try:
            body: object = RichMarkdown(body_source, code_theme="monokai")
        except Exception:
            # Partial fenced block or other parser misery — fall back to
            # escaped plaintext so the stream keeps rendering.
            body = Text(body_source)
        self.update(_Group(glyph, body))


class _ThinkingCell(Static):
    """Reasoning trace — Cursor-style single-line status indicator.

    During streaming, the cell renders as ONE refreshing status line
    (``… thinking · 12s · 248 chars ▌``) — the full reasoning text is
    buffered but not displayed, so a long chain of thought no longer
    floods the transcript with a wall of italic text the user has to
    scroll past.

    On :meth:`finalize` the cell collapses to ``▸ Thought for 12s
    (24 lines)``. Clicking the header expands the buffered reasoning
    in full for users who do want to read it.
    """

    DEFAULT_CSS = "_ThinkingCell { margin: 0 0 1 0; }"

    def __init__(self) -> None:
        super().__init__("")
        self._buffer: str = ""
        self._finalized: bool = False
        self._collapsed: bool = True
        self._started_at = time.monotonic()
        self._finalized_at: float | None = None
        self._limiter = FrameRateLimiter()
        self._refresh(force=True)

    def append(self, text: str) -> None:
        if self._finalized:
            return
        self._buffer += text
        now = time.monotonic()
        if self._limiter.time_until_next_draw(now) is None:
            self._limiter.mark_emitted(now)
            self._refresh(force=False)

    def finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._finalized_at = time.monotonic()
        self._collapsed = True
        self._refresh(force=True)

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        if self._finalized and self._buffer.strip():
            self._collapsed = not self._collapsed
            self._refresh(force=True)

    @property
    def content_text(self) -> str:
        return self._buffer

    def _elapsed(self) -> float:
        end = self._finalized_at if self._finalized_at is not None else time.monotonic()
        return max(0.0, end - self._started_at)

    def _refresh(self, force: bool) -> None:  # noqa: ARG002 — force kept for API symmetry
        elapsed = self._elapsed()
        elapsed_part = f"{elapsed:.1f}s"
        body_text = self._buffer.rstrip()
        body_lines = body_text.splitlines() if body_text else []

        if not self._finalized:
            chars = len(self._buffer)
            stats = f" · {chars} chars" if chars else ""
            line = (
                f"[bright_yellow italic]{_REASONING_OPENER} thinking · "
                f"{elapsed_part}{stats}[/] [blink]{_CURSOR}[/]"
            )
            self.update(line)
            return

        # finalized
        n = len(body_lines)
        caret = "[dim]▸[/]" if self._collapsed else "[dim]▾[/]"
        summary = (
            f"{caret} [dim italic]{_REASONING_OPENER} Thought for "
            f"{elapsed_part}"
        )
        if n:
            summary += f" · {n} line(s)"
        summary += "[/]"

        if self._collapsed or not body_lines:
            self.update(summary)
            return

        rail = "\n".join(
            f"[dim italic]{_REASONING_RAIL} {escape(line)}[/]"
            for line in body_lines
        )
        self.update(f"{summary}\n{rail}")


class _NoticeCell(Static):
    """Structured info / warning / error notice with a coloured rail."""

    _SEVERITY_STYLES: dict[str, str] = {
        "info": "dim bright_cyan",
        "warning": "bright_yellow",
        "error": "bold bright_red",
    }

    DEFAULT_CSS = "_NoticeCell { margin: 0 0 1 0; }"

    def __init__(self, text: str, severity: NoticeSeverity = "info") -> None:
        sev = severity if severity in self._SEVERITY_STYLES else "info"
        style = self._SEVERITY_STYLES[sev]
        super().__init__(f"[{style}]{_DETAIL_RAIL} {escape(text)}[/]")
        self.severity: NoticeSeverity = sev  # type: ignore[assignment]


class _TurnDivider(Static):
    DEFAULT_CSS = "_TurnDivider { margin: 1 0 0 0; }"

    def __init__(self, width: int = 60) -> None:
        super().__init__("[dim bright_black]" + ("─" * width) + "[/]")


class _WelcomeCell(Static):
    """Empty-state greeting shown when the transcript has no messages.

    Mounted on first paint and re-mounted by :meth:`Transcript.clear_messages`;
    removed lazily as soon as any user / notice / tool / assistant content
    arrives. Mirrors the empty-state pattern used by Claude Code and Codex
    TUIs so the cold-start screen feels inviting instead of a void.

    Layout (top → bottom):

    1. Cartoon mascot whale (ASCII art, cyan) — water spout, big eye
    2. 3-line half-block ``DEEPSEEK TUI`` title
    3. Clickable hint line: ``☰  Click anywhere to open the palette``
    4. Two-column key-binding cheat sheet
    5. ``/help`` footnote

    The whole cell is click-bound to :py:meth:`on_click`, which forwards
    to ``DeepSeekTUI.action_command_palette``. ``$boost`` hover styling
    gives a passive visual hint that the surface is interactive.
    """

    DEFAULT_CSS = """
    _WelcomeCell { height: auto; margin: 2 0 1 0; }
    _WelcomeCell:hover { background: $boost; }
    """

    _WHALE = (
        '           .\n'
        '          ":"\n'
        '        ___:____     |"\\/"|  \n'
        "      ,'        `.    \\  /\n"
        "      |  O        \\___/  |\n"
        "    ~^~^~^~^~^~^~^~^~^~^~^~"
    )

    # Hand-crafted 3-row half-block rendering of ``DEEPSEEK TUI``.
    # Each glyph is 3–4 columns wide; a 2-column gap separates the two
    # words. Width: 53 cols. Uses ``█``/``▀``/``▄`` from the U+25xx
    # block — universally available in monospace fonts.
    _TITLE = (
        "█▀▀▄ █▀▀▀ █▀▀▀ █▀▀▄ ▄▀▀▀ █▀▀▀ █▀▀▀ █ ▄▀  ▀█▀ █  █ ▀█▀\n"
        "█  █ █▀▀  █▀▀  █▀▀   ▀▀▄ █▀▀  █▀▀  █▀▄    █  █  █  █ \n"
        "▀▀▀  ▀▀▀▀ ▀▀▀▀ ▀    ▀▀▀  ▀▀▀▀ ▀▀▀▀ ▀  ▀   ▀   ▀▀  ▀▀▀"
    )

    def __init__(self) -> None:
        whale = Text(self._WHALE, style="bold cyan")
        title = Text(self._TITLE, style="bold green")
        hint = Text.from_markup(
            "[bold cyan]☰[/]  [italic bright_white]Click anywhere to open the command "
            "palette[/]  [dim bright_black]·[/]  [italic dim bright_cyan]Ready when you are[/]",
            justify="center",
        )
        hints = Text.from_markup(
            "  [bold bright_green]↵[/]      [bright_white]send[/]                "
            "[bold bright_green]⇧⇥[/]      [bright_white]cycle agent / plan / yolo / ask / goal / workflow[/]\n"
            "  [bold bright_green]/[/]      [bright_white]slash commands[/]      "
            "[bold bright_green]@[/]       [bright_white]mention a workspace file[/]\n"
            "  [bold bright_cyan]Ctrl+K[/]  [bright_white]command palette[/]     "
            "[bold bright_cyan]Ctrl+R[/]  [bright_white]browse sessions[/]\n"
            "  [bold bright_cyan]Ctrl+P[/]  [bright_white]file picker[/]         "
            "[bold bright_cyan]Ctrl+O[/]  [bright_white]switch model[/]\n"
            "  [bold bright_cyan]Ctrl+B[/]  [bright_white]session sidebar[/]     "
            "[bold bright_cyan]Ctrl+I[/]  [bright_white]info sidebar[/]\n"
            "  [bold bright_cyan]Ctrl+T[/]  [bright_white]toggle thinking[/]     "
            "[bold bright_cyan]Ctrl+L[/]  [bright_white]clear transcript[/]",
        )
        footnote = Text.from_markup(
            "[dim bright_black]Type [bold bright_cyan]/help[/] anytime for the full command catalog.[/]",
            justify="center",
        )
        body = _Group(
            Text(""),
            Align.center(whale),
            Text(""),
            Align.center(title),
            Text(""),
            hint,
            Text(""),
            Align.center(hints),
            Text(""),
            footnote,
            Text(""),
        )
        panel = Panel(body, border_style="bright_cyan", padding=(0, 3))
        super().__init__(Align.center(panel))

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        # Forward to the app-level palette action so the welcome card
        # behaves like a giant ``Ctrl+K`` chip. Errors are swallowed
        # because the cell can briefly exist before the engine is wired
        # (no harm if the click lands during that window).
        try:
            self.app.action_command_palette()  # type: ignore[attr-defined]
        except Exception:
            pass


class Transcript(VerticalScroll):
    """Scrollable conversation transcript."""

    DEFAULT_CSS = """
    Transcript {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    MAX_CELLS = 500
    MAX_MESSAGES = 1000

    def __init__(self) -> None:
        super().__init__()
        # ``_current_assistant`` / ``_thinking_cell`` point at the
        # **open** segment of each kind. Each turn can have many of each
        # interleaved with tool calls — every transition between kinds
        # closes the open segment and the next delta starts a fresh
        # cell mounted at the end of the transcript so visible order
        # matches arrival order (mirrors Claude Code CLI's
        # query → think → tool → think → tool → answer layout).
        self._current_assistant: _AssistantCell | None = None
        self._thinking_cell: _ThinkingCell | None = None
        self._tool_cells: dict[str, ToolCell] = {}
        self._subagent_cards: dict[str, object] = {}
        self._subagent_card_state: dict[str, object] = {}
        # Track every thinking cell created during the current turn so
        # ``finalize_message`` can drop them all when ``show_thinking``
        # is off without losing the per-segment chronological layout.
        self._turn_thinking_cells: list[_ThinkingCell] = []
        # Legacy parity contract: tests in phase_e grep for "You:" /
        # "System:" / "Assistant:" substrings in this list.
        self._messages: list[str] = []
        self._current_buffer: str = ""
        self._display_buffer: str = ""
        self._thinking_buffer: str = ""
        self._in_assistant: bool = False
        # Owner can flip this before ``finalize_message`` to control
        # whether the live thinking cells stay collapsed in history or
        # are dropped entirely (mirrors Rust ``ui.show_thinking``).
        self.show_thinking: bool = True
        # Empty-state greeting; lazy-mounted in ``on_mount`` and removed
        # on the first piece of real content.
        self._welcome_cell: _WelcomeCell | None = None

    def on_mount(self) -> None:
        self._show_welcome_if_empty()

    def _show_welcome_if_empty(self) -> None:
        if self._messages or self._welcome_cell is not None:
            return
        self._welcome_cell = _WelcomeCell()
        try:
            self.mount(self._welcome_cell)
        except Exception:
            logger.warning("transcript welcome mount failed", exc_info=True)
            self._welcome_cell = None

    def _hide_welcome(self) -> None:
        if self._welcome_cell is None:
            return
        try:
            self._welcome_cell.remove()
        except Exception:
            logger.debug("transcript welcome remove failed", exc_info=True)
        self._welcome_cell = None

    def _mount_and_scroll(self, widget: Static) -> None:
        try:
            self.mount(widget)
            self.scroll_end(animate=False)
        except Exception:
            logger.warning(
                "transcript mount failed widget=%s",
                type(widget).__name__,
                exc_info=True,
            )

    def _mount_cell(self, widget: Static) -> None:
        try:
            self.mount(widget)
        except Exception:
            logger.warning(
                "transcript mount failed widget=%s",
                type(widget).__name__,
                exc_info=True,
            )

    def _scroll_end_safe(self) -> None:
        try:
            self.scroll_end(animate=False)
        except Exception:
            logger.debug("transcript scroll_end failed", exc_info=True)

    def add_user_message(self, text: str, *, queued: bool = False) -> None:
        self._hide_welcome()
        label = "You (queued)" if queued else "You"
        prefix = "[bold yellow]" if queued else "[bold cyan]"
        self._messages.append(f"{prefix}{label}:[/] {text}")
        cell_text = f"⏳ {text}" if queued else text
        self._mount_and_scroll(_UserCell(cell_text))

    def add_system_message(self, text: str) -> None:
        self._hide_welcome()
        self._messages.append(f"[bold yellow]System:[/] {text}")
        self._mount_and_scroll(_NoticeCell(text, severity="info"))

    def add_notice(
        self, text: str, severity: NoticeSeverity = "info"
    ) -> None:
        """Structured notice — preferred replacement for the System
        catch-all. Preserves the legacy ``_messages`` substring contract
        by prefixing with a capitalised severity label."""
        self._hide_welcome()
        prefix = severity.title()
        self._messages.append(f"[bold]{prefix}:[/] {text}")
        self._mount_and_scroll(_NoticeCell(text, severity=severity))

    def start_assistant_message(self) -> None:
        """Reset per-turn streaming state.

        Note: we no longer eagerly mount an :class:`_AssistantCell`
        here. Empty assistant cells used to claim a slot before any
        thinking / tool events, which made tool cards appear *after*
        the assistant body in the DOM even though they happened first.
        The fix: lazy-mount on the first text delta, and rotate fresh
        cells on every segment transition.
        """
        self._in_assistant = True
        self._current_buffer = ""
        self._display_buffer = ""
        self._thinking_buffer = ""
        self._current_assistant = None
        self._thinking_cell = None
        self._turn_thinking_cells = []

    def _close_open_segments_other_than(self, kind: str) -> None:
        """Finalize the open assistant / thinking segments unless they
        match ``kind`` (``"assistant"`` or ``"thinking"``). Called on
        every delta + tool boundary so segment cells stay in
        chronological order."""
        if kind != "thinking" and self._thinking_cell is not None:
            self._thinking_cell.finalize()
            self._thinking_cell = None
        if kind != "assistant" and self._current_assistant is not None:
            self._current_assistant.finalize()
            self._current_assistant = None

    def append_delta(self, content: str) -> None:
        self._hide_welcome()
        self._current_buffer += content
        new_display = strip_subagent_sentinels(self._current_buffer)
        if (
            len(new_display) >= len(self._display_buffer)
            and new_display.startswith(self._display_buffer)
        ):
            visible = new_display[len(self._display_buffer) :]
        else:
            visible = new_display
        self._display_buffer = new_display
        if not visible:
            return
        if self._current_assistant is None:
            self._close_open_segments_other_than("assistant")
            self._current_assistant = _AssistantCell()
            self._mount_cell(self._current_assistant)
        self._current_assistant.append(visible)
        self._scroll_end_safe()

    def append_thinking(self, content: str) -> None:
        self._hide_welcome()
        self._thinking_buffer += content
        if self._thinking_cell is None:
            self._close_open_segments_other_than("thinking")
            self._thinking_cell = _ThinkingCell()
            self._turn_thinking_cells.append(self._thinking_cell)
            self._mount_cell(self._thinking_cell)
        self._thinking_cell.append(content)
        self._scroll_end_safe()

    def add_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> None:
        self._hide_welcome()
        # A tool call is a segment boundary — close any in-flight text
        # or thinking cells so the tool card slots into chronological
        # position; the next text/thinking delta starts a fresh cell
        # *below* the tool card.
        self._close_open_segments_other_than("")
        entry = (
            f"[bold magenta]⏳ {escape(tool_name)}[/] "
            f"[dim]({tool_call_id[:8]})[/]"
        )
        self._messages.append(entry)
        cell = ToolCell(tool_name, tool_call_id, arguments=arguments)
        self._tool_cells[tool_call_id] = cell
        self._mount_and_scroll(cell)

    def update_tool_result(
        self, tool_call_id: str, content: str, success: bool
    ) -> None:
        cell = self._tool_cells.get(tool_call_id)
        if cell is not None:
            cell.set_result(content, success)
            idx = self._find_tool_message_idx(tool_call_id)
            if idx is not None and idx < len(self._messages):
                icon = "✓" if success else "✗"
                preview = content[:200] + ("..." if len(content) > 200 else "")
                self._messages[idx] = f"{icon} {cell.tool_name}\n{preview}"

    def mark_tool_awaiting_approval(self, tool_call_id: str) -> None:
        """Flip the tool cell header to ``awaiting approval``.

        Used in place of a separate "Approval required" notice line so
        each tool call has a single visible row in the transcript.
        """
        cell = self._tool_cells.get(tool_call_id)
        if cell is not None:
            cell.set_awaiting_approval()

    def mark_tool_approved(self, tool_call_id: str) -> None:
        cell = self._tool_cells.get(tool_call_id)
        if cell is not None:
            cell.set_approved()

    def mark_tool_denied(self, tool_call_id: str, reason: str = "") -> None:
        """Mark the tool cell as denied (user or sandbox) — terminal."""
        cell = self._tool_cells.get(tool_call_id)
        if cell is not None:
            cell.set_denied(reason)
            idx = self._find_tool_message_idx(tool_call_id)
            if idx is not None and idx < len(self._messages):
                self._messages[idx] = f"⊘ {cell.tool_name}\n{reason}"

    def apply_subagent_mailbox(self, message: MailboxMessage) -> None:
        """Mount or update a delegate card for sub-agent progress (#756 UI)."""
        from deepseek_tui.tui.cards import (
            AgentCardWidget,
            DelegateCard,
            apply_to_delegate,
        )

        self._hide_welcome()
        agent_id = message.agent_id
        card = self._subagent_card_state.get(agent_id)
        if card is None and message.kind is MailboxMessageKind.STARTED:
            card = DelegateCard(
                agent_id=agent_id,
                agent_type=message.agent_type or "general",
            )
            self._subagent_card_state[agent_id] = card
            try:
                widget = AgentCardWidget(card)
                self._subagent_cards[agent_id] = widget
                self.mount(widget)
                self.scroll_end(animate=False)
            except Exception:
                return
        elif card is None:
            return
        if not apply_to_delegate(card, message):
            return
        widget = self._subagent_cards.get(agent_id)
        if widget is not None:
            widget.update_card(card)
            self.scroll_end(animate=False)

    def finalize_message(self) -> None:
        if self._thinking_buffer:
            self._messages.append(
                f"[dim italic]Thinking: {self._thinking_buffer}[/]"
            )
        display_text = strip_subagent_sentinels(self._current_buffer)
        if display_text.strip():
            self._messages.append(
                f"[bold green]Assistant:[/] {display_text}"
            )

        # Finalize the in-flight segments first.
        if self._thinking_cell is not None:
            self._thinking_cell.finalize()
        if self._current_assistant is not None:
            self._current_assistant.finalize()
        # Apply the ``show_thinking`` decision to *every* thinking cell
        # mounted during this turn (there can be several across rounds).
        if not self.show_thinking:
            for cell in self._turn_thinking_cells:
                try:
                    cell.remove()
                except Exception:
                    pass
        try:
            self.mount(_TurnDivider())
            self.scroll_end(animate=False)
        except Exception:
            pass

        self._current_assistant = None
        self._thinking_cell = None
        self._turn_thinking_cells = []
        self._current_buffer = ""
        self._display_buffer = ""
        self._thinking_buffer = ""
        self._in_assistant = False
        self._tool_cells.clear()
        self._subagent_cards.clear()
        self._subagent_card_state.clear()
        self._evict_old_cells()

    def _evict_old_cells(self) -> None:
        """Remove oldest DOM children when the transcript exceeds MAX_CELLS."""
        try:
            children = list(self.children)
        except Exception:
            return
        overflow = len(children) - self.MAX_CELLS
        if overflow > 0:
            for child in children[:overflow]:
                try:
                    child.remove()
                except Exception:
                    pass
        if len(self._messages) > self.MAX_MESSAGES:
            self._messages = self._messages[-self.MAX_MESSAGES:]

    def clear_messages(self) -> None:
        self._messages.clear()
        self._current_buffer = ""
        self._display_buffer = ""
        self._thinking_buffer = ""
        self._in_assistant = False
        self._current_assistant = None
        self._thinking_cell = None
        self._turn_thinking_cells = []
        self._tool_cells.clear()
        self._subagent_cards.clear()
        self._subagent_card_state.clear()
        # ``remove_children`` also unmounts the welcome cell, so drop our
        # stale reference and let ``_show_welcome_if_empty`` re-create it.
        self._welcome_cell = None
        try:
            self.remove_children()
        except Exception:
            pass
        self._show_welcome_if_empty()

    def hydrate_from_messages(self, messages: list[object]) -> None:
        """Rebuild transcript cells from persisted ``Message`` objects."""
        from deepseek_tui.protocol.messages import Message

        self.clear_messages()
        for msg in messages:
            if not isinstance(msg, Message):
                continue
            text_parts = [
                getattr(block, "text", "")
                for block in msg.content
                if getattr(block, "type", None) == "text"
            ]
            text = " ".join(part for part in text_parts if part)
            if not text:
                continue
            if msg.role == "user":
                self.add_user_message(text)
            elif msg.role == "assistant":
                self.start_assistant_message()
                self.append_delta(text)
                self.finalize_message()

    def _find_tool_message_idx(self, tool_call_id: str) -> int | None:
        prefix = tool_call_id[:8]
        for i, msg in enumerate(self._messages):
            if prefix in msg:
                return i
        return None
