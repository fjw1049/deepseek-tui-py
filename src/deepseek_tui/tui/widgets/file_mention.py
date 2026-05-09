"""@file mention autocomplete — mirrors Rust ``tui/file_mention.rs``.

Stage 6.6: Detects ``@`` in the composer input and shows a file
completion popup. Files are listed from the working directory.
"""
from __future__ import annotations

import os
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class FileMention(Vertical):
    """Popup for @file autocomplete suggestions."""

    class Selected(Message):
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    DEFAULT_CSS = """
    FileMention {
        dock: bottom;
        height: auto;
        max-height: 10;
        border: tall $accent;
        background: $surface;
        display: none;
    }
    FileMention.visible {
        display: block;
    }
    """

    def __init__(self, working_directory: Path | None = None) -> None:
        super().__init__()
        self._cwd = working_directory or Path.cwd()

    def compose(self) -> ComposeResult:
        yield Static("[bold]Files[/]")
        yield OptionList(id="file-list")

    def show(self, prefix: str = "") -> None:
        """Show file suggestions matching the prefix after ``@``."""
        query = prefix.lstrip("@")
        try:
            option_list = self.query_one("#file-list", OptionList)
            option_list.clear_options()
            matches = self._find_files(query)
            for path in matches[:20]:
                option_list.add_option(Option(path, id=path))
        except Exception:
            pass
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    def _find_files(self, query: str) -> list[str]:
        """List files in working directory matching the query prefix."""
        results: list[str] = []
        query_lower = query.lower()
        try:
            for entry in os.scandir(self._cwd):
                if entry.name.startswith("."):
                    continue
                name = entry.name
                if query_lower and not name.lower().startswith(query_lower):
                    continue
                if entry.is_dir():
                    results.append(f"{name}/")
                else:
                    results.append(name)
        except OSError:
            pass
        results.sort()
        return results

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id:
            self.post_message(self.Selected(event.option.id))
        self.hide()
