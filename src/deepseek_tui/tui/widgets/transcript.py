from __future__ import annotations

from textual.widgets import Static


class Transcript(Static):
    """Displays the conversation transcript."""

    def __init__(self) -> None:
        super().__init__("")
        self._messages: list[str] = []
        self._current_buffer: str = ""
        self._in_assistant: bool = False

    def add_user_message(self, text: str) -> None:
        self._messages.append(f"[bold cyan]You:[/] {text}")
        self._refresh_display()

    def start_assistant_message(self) -> None:
        self._in_assistant = True
        self._current_buffer = ""

    def append_delta(self, content: str) -> None:
        self._current_buffer += content
        self._refresh_display()

    def finalize_message(self) -> None:
        if self._current_buffer:
            self._messages.append(f"[bold green]Assistant:[/] {self._current_buffer}")
        self._current_buffer = ""
        self._in_assistant = False
        self._refresh_display()

    def clear_messages(self) -> None:
        self._messages.clear()
        self._current_buffer = ""
        self._in_assistant = False
        self._refresh_display()

    def _refresh_display(self) -> None:
        parts = list(self._messages)
        if self._in_assistant and self._current_buffer:
            parts.append(f"[bold green]Assistant:[/] {self._current_buffer}[blink]▌[/]")
        self.update("\n\n".join(parts))
