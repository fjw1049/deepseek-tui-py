"""Configuration UI screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, Static


class ConfigScreen(Screen[None]):
    """Configuration interface screen."""

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the config screen layout."""
        with Container(id="config-container"):
            with Vertical(id="config-area"):
                yield Label("Configuration", id="config-title")
                yield Static("Model: [not set]", id="config-model")
                yield Static("Provider: [not set]", id="config-provider")
                yield Static("Approval Mode: [not set]", id="config-approval")
                yield Button("Close", id="config-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "config-close":
            self.app.pop_screen()

    def action_close(self) -> None:
        """Close the config screen."""
        self.app.pop_screen()
