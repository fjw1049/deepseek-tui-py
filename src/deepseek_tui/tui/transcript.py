"""Conversation transcript widget — dual-mode tool cells + dynamic spacing.

Visual hierarchy design (inspired by opencode):

- Assistant text: left-padded 3 chars, markdown rendered, visual focus
- InlineToolCell: zero margin between consecutive inline tools (compact)
- BlockToolCell: margin-top=1, left border panel (breathing room)
- Dynamic spacing: margin computed from previous sibling type
- TurnSummary: replaces TurnDivider with `▣ mode · model · elapsed`

External content passes through ``rich.markup.escape``.
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
from deepseek_tui.tui.tool_cell import BlockToolCell, InlineToolCell, ToolCell
from deepseek_tui.tui.tool_classify import classify_tool
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

# ── Dynamic spacing rules ─────────────────────────────────────────────

_MARGIN_RULES: dict[tuple[str, str], int] = {
    ("inline", "inline"): 0,
    ("inline", "block"): 1,
    ("inline", "assistant"): 1,
    ("inline", "thinking"): 0,
    ("inline", "notice"): 1,
    ("block", "inline"): 1,
    ("block", "block"): 1,
    ("block", "assistant"): 1,
    ("block", "thinking"): 1,
    ("block", "notice"): 1,
    ("assistant", "inline"): 1,
    ("assistant", "block"): 1,
    ("assistant", "assistant"): 1,
    ("assistant", "thinking"): 0,
    ("assistant", "notice"): 1,
    ("thinking", "inline"): 0,
    ("thinking", "block"): 1,
    ("thinking", "assistant"): 1,
    ("thinking", "thinking"): 0,
    ("thinking", "notice"): 0,
    ("notice", "inline"): 0,
    ("notice", "block"): 1,
    ("notice", "assistant"): 1,
    ("notice", "thinking"): 0,
    ("notice", "notice"): 0,
    ("user", "inline"): 1,
    ("user", "block"): 1,
    ("user", "assistant"): 1,
    ("user", "thinking"): 0,
    ("user", "notice"): 0,
}


# ── Cell widgets ──────────────────────────────────────────────────────


class _UserCell(Static):
    DEFAULT_CSS = "_UserCell { margin: 1 0 0 0; }"

    def __init__(self, text: str) -> None:
        super().__init__(f"[bold bright_cyan]{_USER_GLYPH}[/] {escape(text)}")


class _AssistantCell(Static):
    """Streaming assistant cell — left-padded markdown body."""

    DEFAULT_CSS = "_AssistantCell { margin: 0; padding: 0 0 0 3; }"

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
            body = Text(body_source)
        self.update(_Group(glyph, body))


class _ThinkingCell(Static):
    """Reasoning trace — collapsed status during stream, expandable after."""

    DEFAULT_CSS = "_ThinkingCell { margin: 0; padding: 0 0 0 3; }"

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

    def _refresh(self, force: bool) -> None:  # noqa: ARG002
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
    """Structured info / warning / error notice."""

    _SEVERITY_STYLES: dict[str, str] = {
        "info": "dim bright_cyan",
        "warning": "bright_yellow",
        "error": "bold bright_red",
    }

    DEFAULT_CSS = "_NoticeCell { margin: 0; padding: 0 0 0 3; }"

    def __init__(self, text: str, severity: NoticeSeverity = "info") -> None:
        sev = severity if severity in self._SEVERITY_STYLES else "info"
        style = self._SEVERITY_STYLES[sev]
        super().__init__(f"[{style}]{_DETAIL_RAIL} {escape(text)}[/]")
        self.severity: NoticeSeverity = sev  # type: ignore[assignment]


class _TurnSummary(Static):
    """Turn-end metadata line: ▣ mode · model · elapsed · tokens."""

    DEFAULT_CSS = "_TurnSummary { margin: 1 0 1 0; padding: 0 0 0 3; }"

    def __init__(
        self,
        mode: str = "",
        model: str = "",
        elapsed: float = 0.0,
        tokens: int = 0,
        cost: float | None = None,
    ) -> None:
        parts: list[str] = []
        parts.append("[dim]▣[/]")
        if mode:
            parts.append(f"[bold]{escape(mode)}[/]")
        if model:
            parts.append(f"[dim]· {escape(model)}[/]")
        if elapsed > 0.1:
            parts.append(f"[dim]· {elapsed:.1f}s[/]")
        if tokens:
            if tokens >= 1000:
                parts.append(f"[dim]· {tokens / 1000:.1f}k tokens[/]")
            else:
                parts.append(f"[dim]· {tokens} tokens[/]")
        if cost is not None and cost > 0:
            parts.append(f"[dim]· ${cost:.4f}[/]")
        super().__init__(" ".join(parts))


class _TurnDivider(Static):
    """Legacy turn divider — kept for compatibility but no longer mounted."""
    DEFAULT_CSS = "_TurnDivider { margin: 1 0 0 0; }"

    def __init__(self, width: int = 60) -> None:
        super().__init__("[dim bright_black]" + ("─" * width) + "[/]")


class _WelcomeCell(Static):
    """Empty-state greeting shown when the transcript has no messages."""

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
            "[bold bright_green]⇧⇥[/]      [bright_white]cycle agent / plan / yolo / ask / workflow[/]\n"
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
        try:
            self.app.action_command_palette()  # type: ignore[attr-defined]
        except Exception:
            pass


# ── Main Transcript container ─────────────────────────────────────────


class Transcript(VerticalScroll):
    """Scrollable conversation transcript with dynamic spacing."""

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
        self._current_assistant: _AssistantCell | None = None
        self._thinking_cell: _ThinkingCell | None = None
        self._tool_cells: dict[str, InlineToolCell | BlockToolCell] = {}
        self._subagent_cards: dict[str, object] = {}
        self._subagent_card_state: dict[str, object] = {}
        self._turn_thinking_cells: list[_ThinkingCell] = []
        # Legacy parity
        self._messages: list[str] = []
        self._current_buffer: str = ""
        self._display_buffer: str = ""
        self._thinking_buffer: str = ""
        self._in_assistant: bool = False
        self.show_thinking: bool = True
        self.show_details: bool = True
        self._welcome_cell: _WelcomeCell | None = None
        # Dynamic spacing state
        self._last_mounted_type: str = ""

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

    def _compute_margin(self, new_type: str) -> int:
        """Compute margin-top based on previous sibling type."""
        if not self._last_mounted_type:
            return 0
        return _MARGIN_RULES.get((self._last_mounted_type, new_type), 1)

    def _mount_with_spacing(self, widget: Static, cell_type: str) -> None:
        """Mount widget with dynamic margin based on context."""
        margin_top = self._compute_margin(cell_type)
        widget.styles.margin = (margin_top, 0, 0, 0)
        self._last_mounted_type = cell_type
        try:
            self.mount(widget)
        except Exception:
            logger.warning(
                "transcript mount failed widget=%s",
                type(widget).__name__,
                exc_info=True,
            )

    def _mount_and_scroll(self, widget: Static, cell_type: str) -> None:
        self._mount_with_spacing(widget, cell_type)
        self._scroll_end_safe()

    def _mount_cell(self, widget: Static, cell_type: str) -> None:
        self._mount_with_spacing(widget, cell_type)

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
        cell = _UserCell(cell_text)
        self._last_mounted_type = "user"
        cell.styles.margin = (1, 0, 0, 0)
        try:
            self.mount(cell)
            self.scroll_end(animate=False)
        except Exception:
            pass

    def add_system_message(self, text: str) -> None:
        self._hide_welcome()
        self._messages.append(f"[bold yellow]System:[/] {text}")
        self._mount_and_scroll(_NoticeCell(text, severity="info"), "notice")

    def add_notice(
        self, text: str, severity: NoticeSeverity = "info"
    ) -> None:
        self._hide_welcome()
        prefix = severity.title()
        self._messages.append(f"[bold]{prefix}:[/] {text}")
        self._mount_and_scroll(_NoticeCell(text, severity=severity), "notice")

    def start_assistant_message(self) -> None:
        self._in_assistant = True
        self._current_buffer = ""
        self._display_buffer = ""
        self._thinking_buffer = ""
        self._current_assistant = None
        self._thinking_cell = None
        self._turn_thinking_cells = []

    def _close_open_segments_other_than(self, kind: str) -> None:
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
            visible = new_display[len(self._display_buffer):]
        else:
            visible = new_display
        self._display_buffer = new_display
        if not visible:
            return
        if self._current_assistant is None:
            self._close_open_segments_other_than("assistant")
            self._current_assistant = _AssistantCell()
            self._mount_cell(self._current_assistant, "assistant")
        self._current_assistant.append(visible)
        self._scroll_end_safe()

    def append_thinking(self, content: str) -> None:
        self._hide_welcome()
        self._thinking_buffer += content
        if self._thinking_cell is None:
            self._close_open_segments_other_than("thinking")
            self._thinking_cell = _ThinkingCell()
            self._turn_thinking_cells.append(self._thinking_cell)
            self._mount_cell(self._thinking_cell, "thinking")
        self._thinking_cell.append(content)
        self._scroll_end_safe()

    def add_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> None:
        self._hide_welcome()
        self._close_open_segments_other_than("")

        entry = (
            f"[bold magenta]⏳ {escape(tool_name)}[/] "
            f"[dim]({tool_call_id[:8]})[/]"
        )
        self._messages.append(entry)

        # Route to InlineToolCell or BlockToolCell based on classification
        display = classify_tool(tool_name)
        if display.mode == "inline":
            cell = InlineToolCell(tool_name, tool_call_id, arguments, display=display)
            self._tool_cells[tool_call_id] = cell
            self._mount_and_scroll(cell, "inline")
        else:
            cell = BlockToolCell(tool_name, tool_call_id, arguments, display=display)
            self._tool_cells[tool_call_id] = cell
            self._mount_and_scroll(cell, "block")

    def update_tool_result(
        self, tool_call_id: str, content: str, success: bool
    ) -> None:
        cell = self._tool_cells.get(tool_call_id)
        if cell is not None:
            # For exec_shell: if it was inline but has output, upgrade to block
            if (
                isinstance(cell, InlineToolCell)
                and cell.tool_name == "exec_shell"
                and content.strip()
                and success
            ):
                # Upgrade: remove inline, mount block
                display = classify_tool(cell.tool_name, has_output=True)
                if display.mode == "block":
                    try:
                        cell.remove()
                    except Exception:
                        pass
                    new_cell = BlockToolCell(
                        cell.tool_name, tool_call_id, cell._arguments, display=display
                    )
                    new_cell.set_result(content, success)
                    self._tool_cells[tool_call_id] = new_cell
                    self._mount_and_scroll(new_cell, "block")
                    self._update_tool_message(tool_call_id, cell.tool_name, content, success)
                    return

            cell.set_result(content, success)
            self._update_tool_message(tool_call_id, cell.tool_name, content, success)

    def _update_tool_message(
        self, tool_call_id: str, tool_name: str, content: str, success: bool
    ) -> None:
        idx = self._find_tool_message_idx(tool_call_id)
        if idx is not None and idx < len(self._messages):
            icon = "✓" if success else "✗"
            preview = content[:200] + ("..." if len(content) > 200 else "")
            self._messages[idx] = f"{icon} {tool_name}\n{preview}"

    def mark_tool_awaiting_approval(self, tool_call_id: str) -> None:
        cell = self._tool_cells.get(tool_call_id)
        if cell is not None:
            cell.set_awaiting_approval()

    def mark_tool_approved(self, tool_call_id: str) -> None:
        cell = self._tool_cells.get(tool_call_id)
        if cell is not None:
            cell.set_approved()

    def mark_tool_denied(self, tool_call_id: str, reason: str = "") -> None:
        cell = self._tool_cells.get(tool_call_id)
        if cell is not None:
            cell.set_denied(reason)
            idx = self._find_tool_message_idx(tool_call_id)
            if idx is not None and idx < len(self._messages):
                self._messages[idx] = f"⊘ {cell.tool_name}\n{reason}"

    def apply_subagent_mailbox(self, message: MailboxMessage) -> None:
        """Mount or update a delegate card for sub-agent progress."""
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

    def finalize_message(
        self,
        *,
        mode: str = "",
        model: str = "",
        elapsed: float = 0.0,
        tokens: int = 0,
        cost: float | None = None,
    ) -> None:
        if self._thinking_buffer:
            self._messages.append(
                f"[dim italic]Thinking: {self._thinking_buffer}[/]"
            )
        display_text = strip_subagent_sentinels(self._current_buffer)
        if display_text.strip():
            self._messages.append(
                f"[bold green]Assistant:[/] {display_text}"
            )

        if self._thinking_cell is not None:
            self._thinking_cell.finalize()
        if self._current_assistant is not None:
            self._current_assistant.finalize()

        if not self.show_thinking:
            for cell in self._turn_thinking_cells:
                try:
                    cell.remove()
                except Exception:
                    pass

        # Mount turn summary instead of plain divider
        try:
            summary = _TurnSummary(
                mode=mode, model=model, elapsed=elapsed,
                tokens=tokens, cost=cost,
            )
            self.mount(summary)
            self._last_mounted_type = ""
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
        self._welcome_cell = None
        self._last_mounted_type = ""
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

    def toggle_details(self) -> None:
        """Toggle show_details: hide/show completed inline tools."""
        self.show_details = not self.show_details
        # Apply visibility to all existing inline tool cells
        try:
            for child in self.children:
                if isinstance(child, InlineToolCell) and child._status == "done":
                    child.display = self.show_details
        except Exception:
            pass

    def _find_tool_message_idx(self, tool_call_id: str) -> int | None:
        prefix = tool_call_id[:8]
        for i, msg in enumerate(self._messages):
            if prefix in msg:
                return i
        return None
