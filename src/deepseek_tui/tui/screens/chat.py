"""Chat screen for the TUI application."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen

from deepseek_tui.tui.widgets import Composer, StatusBar, Transcript


class ChatScreen(Screen[None]):
    """Main chat interface screen."""

    BINDINGS = [
        ("ctrl+n", "new_session", "New Session"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the chat screen layout."""
        with Container(id="chat-container"):
            with Vertical(id="main-area"):
                yield Transcript()
                yield Composer()
            yield StatusBar()

    def action_new_session(self) -> None:
        """Start a new chat session."""
        transcript = self.query_one(Transcript)
        transcript.clear_messages()
        composer = self.query_one(Composer)
        composer.clear()

    def action_cancel(self) -> None:
        """Cancel current operation."""
        pass

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()
