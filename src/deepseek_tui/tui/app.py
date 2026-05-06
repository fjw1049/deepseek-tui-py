from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from deepseek_tui.engine.events import (
    TextDeltaEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.ops import SendMessageOp
from deepseek_tui.tui.widgets.composer import Composer
from deepseek_tui.tui.widgets.status_bar import StatusBar
from deepseek_tui.tui.widgets.transcript import Transcript


class DeepSeekTUI(App[None]):
    """Main TUI application."""

    TITLE = "DeepSeek TUI"
    CSS = """
    Transcript {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    Composer {
        dock: bottom;
        height: auto;
        max-height: 10;
        padding: 0 1;
    }
    StatusBar {
        dock: bottom;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+n", "new_session", "New Session"),
    ]

    def __init__(self, handle: EngineHandle) -> None:
        super().__init__()
        self.handle = handle

    def compose(self) -> ComposeResult:
        yield Header()
        yield Transcript()
        yield StatusBar()
        yield Composer()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Composer).focus()

    async def on_composer_submitted(self, event: Composer.Submitted) -> None:
        transcript = self.query_one(Transcript)
        transcript.add_user_message(event.text)
        await self.handle.send_op(SendMessageOp(content=event.text))
        self.run_worker(self._listen_events())

    async def _listen_events(self) -> None:
        transcript = self.query_one(Transcript)
        status = self.query_one(StatusBar)
        async for event in self.handle.events():
            if isinstance(event, TurnStartedEvent):
                status.set_status("thinking...")
                transcript.start_assistant_message()
            elif isinstance(event, TextDeltaEvent):
                transcript.append_delta(event.text)
            elif isinstance(event, TurnCompleteEvent):
                status.set_status("ready")
                transcript.finalize_message()
                break

    def action_new_session(self) -> None:
        transcript = self.query_one(Transcript)
        transcript.clear_messages()
