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

from deepseek_tui.tui.frame_rate_limiter import FrameRateLimiter
from deepseek_tui.tui.widgets.tool_cell import ToolCell

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
        super().__init__(f"[bold]{_USER_GLYPH}[/] {escape(text)}")


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
        glyph_style = "green" if self._finalized else "bold green"
        glyph = Text(_ASSISTANT_GLYPH, style=glyph_style)
        if not self._buffer.strip():
            cursor_text = (
                Text("", style="dim")
                if self._finalized
                else Text(_CURSOR, style="bold green blink")
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
    """Reasoning trace. Header line + ``╎ `` rail per body line.

    During streaming the full body is shown so the user can follow the
    model's reasoning live. After :meth:`finalize` the cell becomes
    click-foldable: a single click toggles between the full body and a
    header-only "(N lines hidden)" view, matching the
    :class:`ToolCell` fold semantics so the user has one consistent
    gesture for hiding noisy segments from history.
    """

    DEFAULT_CSS = "_ThinkingCell { margin: 0 0 1 0; }"

    def __init__(self) -> None:
        super().__init__("")
        self._buffer: str = ""
        self._finalized: bool = False
        self._collapsed: bool = False
        self._started_at = time.monotonic()
        self._refresh()

    def append(self, text: str) -> None:
        if self._finalized:
            return
        self._buffer += text
        self._refresh()

    def finalize(self) -> None:
        self._finalized = True
        # Auto-collapse finished thinking so the eye lands on the
        # assistant's actual answer. Body is preserved and one click
        # on the header expands it again.
        if self._buffer.strip():
            self._collapsed = True
        self._refresh()

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        # Only allow folding after the stream is done — collapsing
        # mid-stream would hide content the user is actively reading.
        if self._finalized and self._buffer.strip():
            self._collapsed = not self._collapsed
            self._refresh()

    @property
    def content_text(self) -> str:
        return self._buffer

    def _refresh(self) -> None:
        state = "done" if self._finalized else "thinking"
        elapsed = time.monotonic() - self._started_at
        elapsed_part = f" · {elapsed:.0f}s" if elapsed >= 1.0 else ""
        header_style = "dim italic" if self._finalized else "yellow italic"
        body_text = self._buffer.rstrip()
        body_lines = body_text.splitlines() if body_text else []
        caret = ""
        if self._finalized and body_lines:
            caret = "[dim]▸[/] " if self._collapsed else "[dim]▾[/] "
        header = (
            f"{caret}[{header_style}]{_REASONING_OPENER} {state}{elapsed_part}[/]"
        )

        if not body_text:
            tail = "" if self._finalized else f" [blink]{_CURSOR}[/]"
            placeholder = (
                f"[dim italic]{_REASONING_RAIL} reasoning in progress…{tail}[/]"
            )
            self.update(f"{header}\n{placeholder}")
            return

        if self._collapsed and self._finalized:
            n = len(body_lines)
            self.update(
                f"{header}  [dim italic](hidden: {n} line(s))[/]"
            )
            return

        rail = "\n".join(
            f"[dim italic]{_REASONING_RAIL} {escape(line)}[/]"
            for line in body_lines
        )
        if not self._finalized:
            rail = f"{rail} [blink]{_CURSOR}[/]"
        self.update(f"{header}\n{rail}")


class _NoticeCell(Static):
    """Structured info / warning / error notice with a coloured rail."""

    _SEVERITY_STYLES: dict[str, str] = {
        "info": "dim",
        "warning": "yellow",
        "error": "bold red",
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
        super().__init__("[dim]" + ("─" * width) + "[/]")


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

    # Cartoon whale. ~30 cols × 8 rows. Trailing whitespace per line is
    # deliberate — it preserves the silhouette when ``Align.center``
    # centres the multi-line block as one unit.
    _WHALE = (
        "                  o\n"
        "                 o\n"
        "               _____\n"
        "           _.-'     '-.___\n"
        "         ,'   ●              '-._\n"
        "         (         ‿              )\n"
        "          '.___________________..-'\n"
        "              ~  ~  ~  ~  ~  ~"
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
        whale = Text(self._WHALE, style="cyan")
        title = Text(self._TITLE, style="bold green")
        hint = Text.from_markup(
            "[bold green]☰[/]  [italic]Click anywhere to open the command "
            "palette[/]  [dim]·[/]  [italic dim]Ready when you are[/]",
            justify="center",
        )
        hints = Text.from_markup(
            "  [bold]↵[/]      send                "
            "[bold]⇧⇥[/]      cycle agent / plan / yolo / ask\n"
            "  [bold]/[/]      slash commands      "
            "[bold]@[/]       mention a workspace file\n"
            "  [bold]Ctrl+K[/]  command palette     "
            "[bold]Ctrl+R[/]  browse sessions\n"
            "  [bold]Ctrl+P[/]  file picker         "
            "[bold]Ctrl+O[/]  switch model\n"
            "  [bold]Ctrl+B[/]  session sidebar     "
            "[bold]Ctrl+I[/]  info sidebar\n"
            "  [bold]Ctrl+T[/]  toggle thinking     "
            "[bold]Ctrl+L[/]  clear transcript",
        )
        footnote = Text.from_markup(
            "[dim]Type [bold]/help[/] anytime for the full command catalog.[/]",
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
        panel = Panel(body, border_style="dim cyan", padding=(0, 3))
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
        # Track every thinking cell created during the current turn so
        # ``finalize_message`` can drop them all when ``show_thinking``
        # is off without losing the per-segment chronological layout.
        self._turn_thinking_cells: list[_ThinkingCell] = []
        # Legacy parity contract: tests in phase_e grep for "You:" /
        # "System:" / "Assistant:" substrings in this list.
        self._messages: list[str] = []
        self._current_buffer: str = ""
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
            self._welcome_cell = None

    def _hide_welcome(self) -> None:
        if self._welcome_cell is None:
            return
        try:
            self._welcome_cell.remove()
        except Exception:
            pass
        self._welcome_cell = None

    def add_user_message(self, text: str, *, queued: bool = False) -> None:
        self._hide_welcome()
        label = "You (queued)" if queued else "You"
        prefix = "[bold yellow]" if queued else "[bold cyan]"
        self._messages.append(f"{prefix}{label}:[/] {text}")
        try:
            cell_text = f"⏳ {text}" if queued else text
            self.mount(_UserCell(cell_text))
            self.scroll_end(animate=False)
        except Exception:
            pass

    def add_system_message(self, text: str) -> None:
        self._hide_welcome()
        self._messages.append(f"[bold yellow]System:[/] {text}")
        try:
            self.mount(_NoticeCell(text, severity="info"))
            self.scroll_end(animate=False)
        except Exception:
            pass

    def add_notice(
        self, text: str, severity: NoticeSeverity = "info"
    ) -> None:
        """Structured notice — preferred replacement for the System
        catch-all. Preserves the legacy ``_messages`` substring contract
        by prefixing with a capitalised severity label."""
        self._hide_welcome()
        prefix = severity.title()
        self._messages.append(f"[bold]{prefix}:[/] {text}")
        try:
            self.mount(_NoticeCell(text, severity=severity))
            self.scroll_end(animate=False)
        except Exception:
            pass

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
        if self._current_assistant is None:
            self._close_open_segments_other_than("assistant")
            self._current_assistant = _AssistantCell()
            try:
                self.mount(self._current_assistant)
            except Exception:
                pass
        self._current_assistant.append(content)
        try:
            self.scroll_end(animate=False)
        except Exception:
            pass

    def append_thinking(self, content: str) -> None:
        self._hide_welcome()
        self._thinking_buffer += content
        if self._thinking_cell is None:
            self._close_open_segments_other_than("thinking")
            self._thinking_cell = _ThinkingCell()
            self._turn_thinking_cells.append(self._thinking_cell)
            try:
                self.mount(self._thinking_cell)
            except Exception:
                pass
        self._thinking_cell.append(content)
        try:
            self.scroll_end(animate=False)
        except Exception:
            pass

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
        try:
            self.mount(cell)
            self.scroll_end(animate=False)
        except Exception:
            pass

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

    def finalize_message(self) -> None:
        if self._thinking_buffer:
            self._messages.append(
                f"[dim italic]Thinking: {self._thinking_buffer}[/]"
            )
        if self._current_buffer:
            self._messages.append(
                f"[bold green]Assistant:[/] {self._current_buffer}"
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
        self._thinking_buffer = ""
        self._in_assistant = False
        self._tool_cells.clear()
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
        self._thinking_buffer = ""
        self._in_assistant = False
        self._current_assistant = None
        self._thinking_cell = None
        self._turn_thinking_cells = []
        self._tool_cells.clear()
        # ``remove_children`` also unmounts the welcome cell, so drop our
        # stale reference and let ``_show_welcome_if_empty`` re-create it.
        self._welcome_cell = None
        try:
            self.remove_children()
        except Exception:
            pass
        self._show_welcome_if_empty()

    def _find_tool_message_idx(self, tool_call_id: str) -> int | None:
        prefix = tool_call_id[:8]
        for i, msg in enumerate(self._messages):
            if prefix in msg:
                return i
        return None
