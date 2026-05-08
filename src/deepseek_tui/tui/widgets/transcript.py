"""Conversation transcript widget — mirrors Rust ``tui/transcript.rs``.

Stage 6.2: VerticalScroll container with individual message widgets.
Each message is a distinct cell (user / assistant / system / tool) for
proper scrolling and rendering. Markdown rendering uses Textual's
built-in ``Markdown`` widget for assistant responses.
"""
from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static

from deepseek_tui.tui.widgets.tool_cell import ToolCell


class _UserCell(Static):
    DEFAULT_CSS = "._UserCell { margin: 0 0 1 0; }"

    def __init__(self, text: str) -> None:
        super().__init__(f"[bold cyan]You:[/] {text}")


class _SystemCell(Static):
    DEFAULT_CSS = "._SystemCell { margin: 0 0 1 0; color: $warning; }"

    def __init__(self, text: str) -> None:
        super().__init__(f"[bold yellow]System:[/] {text}")


class _ThinkingCell(Static):
    DEFAULT_CSS = "._ThinkingCell { margin: 0 0 1 0; color: $text-muted; }"

    def __init__(self, text: str) -> None:
        super().__init__(f"[dim italic]Thinking: {text}[/]")


class _AssistantCell(Static):
    """Displays assistant response with Rich markup (live-updating)."""

    DEFAULT_CSS = "_AssistantCell { margin: 0 0 1 0; }"

    def __init__(self) -> None:
        super().__init__("")
        self._buffer: str = ""
        self._finalized: bool = False

    def append(self, text: str) -> None:
        self._buffer += text
        self._refresh()

    def finalize(self) -> None:
        self._finalized = True
        self._refresh()

    def _refresh(self) -> None:
        cursor = "" if self._finalized else "[blink]▌[/]"
        self.update(f"[bold green]Assistant:[/] {self._buffer}{cursor}")


class Transcript(VerticalScroll):
    """Displays the conversation transcript as a scrollable list of cells."""

    DEFAULT_CSS = """
    Transcript {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._current_assistant: _AssistantCell | None = None
        self._thinking_cell: _ThinkingCell | None = None
        self._tool_cells: dict[str, ToolCell] = {}
        # Legacy compat
        self._messages: list[str] = []
        self._current_buffer: str = ""
        self._thinking_buffer: str = ""
        self._in_assistant: bool = False

    def add_user_message(self, text: str) -> None:
        self._messages.append(f"[bold cyan]You:[/] {text}")
        try:
            self.mount(_UserCell(text))
            self.scroll_end(animate=False)
        except Exception:
            pass

    def add_system_message(self, text: str) -> None:
        self._messages.append(f"[bold yellow]System:[/] {text}")
        try:
            self.mount(_SystemCell(text))
            self.scroll_end(animate=False)
        except Exception:
            pass

    def start_assistant_message(self) -> None:
        self._in_assistant = True
        self._current_buffer = ""
        self._thinking_buffer = ""
        self._current_assistant = _AssistantCell()
        self._thinking_cell = None
        try:
            self.mount(self._current_assistant)
        except Exception:
            pass

    def append_delta(self, content: str) -> None:
        self._current_buffer += content
        if self._current_assistant is not None:
            self._current_assistant.append(content)
            try:
                self.scroll_end(animate=False)
            except Exception:
                pass

    def append_thinking(self, content: str) -> None:
        self._thinking_buffer += content
        if self._thinking_cell is None:
            self._thinking_cell = _ThinkingCell(content)
            try:
                self.mount(self._thinking_cell)
            except Exception:
                pass
        else:
            self._thinking_cell.update(
                f"[dim italic]Thinking: {self._thinking_buffer}[/]"
            )

    def add_tool_call(
        self, tool_call_id: str, tool_name: str, arguments: dict[str, object]
    ) -> None:
        entry = f"[bold magenta]⏳ {tool_name}[/] [dim]({tool_call_id[:8]})[/]"
        self._messages.append(entry)
        cell = ToolCell(tool_name, tool_call_id)
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

    def finalize_message(self) -> None:
        if self._thinking_buffer:
            self._messages.append(
                f"[dim italic]Thinking: {self._thinking_buffer}[/]"
            )
        if self._current_buffer:
            self._messages.append(
                f"[bold green]Assistant:[/] {self._current_buffer}"
            )
        if self._current_assistant is not None:
            self._current_assistant.finalize()
        self._current_assistant = None
        self._thinking_cell = None
        self._current_buffer = ""
        self._thinking_buffer = ""
        self._in_assistant = False
        self._tool_cells.clear()

    def clear_messages(self) -> None:
        self._messages.clear()
        self._current_buffer = ""
        self._thinking_buffer = ""
        self._in_assistant = False
        self._current_assistant = None
        self._thinking_cell = None
        self._tool_cells.clear()
        try:
            self.remove_children()
        except Exception:
            pass

    def _find_tool_message_idx(self, tool_call_id: str) -> int | None:
        prefix = tool_call_id[:8]
        for i, msg in enumerate(self._messages):
            if prefix in msg:
                return i
        return None
