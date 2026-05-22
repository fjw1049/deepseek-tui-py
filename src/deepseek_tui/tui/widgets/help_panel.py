"""Help / keybinds panel — mirrors Rust help screen.

Provides a modal overlay showing all keybindings and available commands,
with section grouping and scrollable content.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

KEYBIND_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "General",
        [
            ("Ctrl+C", "Quit application"),
            ("Ctrl+N", "New session"),
            ("Ctrl+K", "Command palette"),
            ("Ctrl+B", "Toggle sidebar"),
            ("?", "Show this help"),
            ("Escape", "Close panel / cancel"),
        ],
    ),
    (
        "Navigation",
        [
            ("↑ / ↓", "Scroll transcript"),
            ("Page Up / Page Down", "Scroll page"),
            ("Home / End", "Jump to top / bottom"),
            ("Tab", "Next focusable widget"),
            ("Shift+Tab", "Previous focusable widget"),
        ],
    ),
    (
        "Composer",
        [
            ("Enter", "Send message"),
            ("Ctrl+Enter", "New line"),
            ("↑", "Previous history entry"),
            ("↓", "Next history entry"),
            ("/", "Slash command (when empty)"),
            ("@", "File mention"),
        ],
    ),
    (
        "Sidebar",
        [
            ("Enter", "Open session"),
            ("d", "Delete session"),
            ("a", "Archive / unarchive"),
            ("r", "Rename session"),
            ("Escape", "Close sidebar"),
        ],
    ),
    (
        "During Response",
        [
            ("Ctrl+C", "Cancel current turn"),
            ("Ctrl+Z", "Interrupt and undo"),
        ],
    ),
    (
        "Pickers",
        [
            ("↑ / ↓", "Navigate options"),
            ("Enter", "Select"),
            ("Escape", "Cancel"),
            ("Type", "Filter options"),
        ],
    ),
]


class HelpPanel(ModalScreen[None]):
    """Full-screen modal showing keybindings and help."""

    DEFAULT_CSS = """
    HelpPanel {
        align: center middle;
    }
    HelpPanel > VerticalScroll {
        width: 70;
        max-width: 90%;
        height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    HelpPanel .help-title {
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    HelpPanel .help-section {
        text-style: bold;
        color: $accent;
        margin-top: 1;
    }
    HelpPanel .help-binding {
        margin-left: 2;
    }
    HelpPanel .help-footer {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_help", "Close"),
        Binding("q", "dismiss_help", "Close"),
        Binding("question_mark", "dismiss_help", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("[bold]Keybindings & Help[/]", classes="help-title")
            for section_name, bindings in KEYBIND_SECTIONS:
                yield Static(f"[bold]{section_name}[/]", classes="help-section")
                for key, desc in bindings:
                    yield Static(
                        f"  [cyan]{key:<20}[/] {desc}",
                        classes="help-binding",
                    )
            yield Static("")
            yield _SlashCommandHelp()
            yield Static(
                "[dim]Press Escape or ? to close[/]", classes="help-footer"
            )

    def action_dismiss_help(self) -> None:
        self.dismiss(None)


class _SlashCommandHelp(Static):
    """Shows available slash commands in the help panel."""

    def __init__(self) -> None:
        super().__init__("")

    def on_mount(self) -> None:
        try:
            from deepseek_tui.tui.commands import REGISTRY

            lines = ["[bold]Slash Commands[/]\n"]
            for entry in REGISTRY:
                lines.append(f"  [green]{entry.name:<16}[/] {entry.description}")
            self.update("\n".join(lines))
        except Exception:
            self.update("[dim]Slash commands unavailable[/]")
