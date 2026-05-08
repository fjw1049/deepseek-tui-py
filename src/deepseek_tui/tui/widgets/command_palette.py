"""Command palette widget — mirrors Rust ``tui/command_palette.rs``.

Stage 6.6: Ctrl+K style command palette for quick access to slash
commands, model switching, and other actions.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from deepseek_tui.tui.commands import get_completions


class CommandPalette(ModalScreen[str | None]):
    """Modal command palette activated by Ctrl+K."""

    CSS = """
    CommandPalette {
        align: center top;
    }
    #palette-container {
        width: 70;
        max-height: 20;
        margin-top: 3;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    #palette-input {
        margin-bottom: 1;
    }
    """

    class Selected(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-container"):
            yield Input(placeholder="Type a command...", id="palette-input")
            completions = get_completions("/")
            options = [
                Option(f"{cmd}  [dim]{desc}[/]", id=cmd)
                for cmd, desc in completions
            ]
            yield OptionList(*options, id="palette-list")

    def on_mount(self) -> None:
        self.query_one("#palette-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        text = event.value.strip()
        prefix = text if text.startswith("/") else f"/{text}"
        completions = get_completions(prefix)
        try:
            option_list = self.query_one("#palette-list", OptionList)
            option_list.clear_options()
            for cmd, desc in completions:
                option_list.add_option(Option(f"{cmd}  [dim]{desc}[/]", id=cmd))
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            cmd = text if text.startswith("/") else f"/{text}"
            self.dismiss(cmd)
        else:
            self.dismiss(None)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id:
            self.dismiss(event.option.id)

    def on_key(self, event: object) -> None:
        from textual.events import Key
        if isinstance(event, Key) and event.key == "escape":
            self.dismiss(None)
