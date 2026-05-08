from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from deepseek_tui.tui.commands import get_completions


class SlashMenu(Vertical):
    """Popup menu for slash commands.

    Driven by the central :mod:`deepseek_tui.tui.commands` registry instead
    of a hardcoded list. The ``filter_text`` parameter on :meth:`show` is
    forwarded to :func:`get_completions` so the menu narrows as the user
    types.
    """

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

    def compose(self) -> ComposeResult:
        yield Static("[bold]Commands[/]")
        completions = get_completions("/")
        options = [
            Option(f"{cmd}  [dim]{desc}[/]", id=cmd)
            for cmd, desc in completions
        ]
        yield OptionList(*options)

    def show(self, filter_text: str = "") -> None:
        prefix = filter_text if filter_text.startswith("/") else "/"
        completions = get_completions(prefix)
        try:
            option_list = self.query_one(OptionList)
            option_list.clear_options()
            for cmd, desc in completions:
                option_list.add_option(Option(f"{cmd}  [dim]{desc}[/]", id=cmd))
        except Exception:
            pass
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.post_message(self.Selected(event.option.id))
        self.hide()
