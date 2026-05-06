from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """Bottom status bar showing current state."""

    def __init__(self) -> None:
        super().__init__("[dim]ready[/]")

    def set_status(self, text: str) -> None:
        self.update(f"[dim]{text}[/]")
