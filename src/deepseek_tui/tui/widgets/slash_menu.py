from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class SlashMenu(Vertical):
    """Popup menu for slash commands."""

    class Selected(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    DEFAULT_CSS = """
    SlashMenu {
        dock: bottom;
        height: auto;
        max-height: 12;
        border: tall $accent;
        background: $surface;
        display: none;
    }
    SlashMenu.visible {
        display: block;
    }
    """

    COMMANDS = [
        ("/help", "Show available commands"),
        ("/clear", "Clear conversation"),
        ("/config", "Open configuration"),
        ("/export", "Export conversation"),
        ("/model", "Switch model"),
        ("/session", "Session management"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("[bold]Commands[/]")
        options = [Option(f"{cmd}  [dim]{desc}[/]", id=cmd) for cmd, desc in self.COMMANDS]
        yield OptionList(*options)

    def show(self, filter_text: str = "") -> None:
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.post_message(self.Selected(event.option.id))
        self.hide()
