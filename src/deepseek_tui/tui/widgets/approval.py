from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ApprovalDialog(ModalScreen[bool]):
    """Modal dialog for tool execution approval."""

    CSS = """
    ApprovalDialog {
        align: center middle;
    }
    #approval-container {
        width: 60;
        height: auto;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    #approval-buttons {
        margin-top: 1;
        align: center middle;
    }
    """

    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.reason = reason

    def compose(self) -> ComposeResult:
        with Horizontal(id="approval-container"):
            yield Label(
                f"[bold]Approve tool call?[/]\n\nTool: {self.tool_name}\nReason: {self.reason}",
            )
        with Horizontal(id="approval-buttons"):
            yield Button("Approve", variant="success", id="approve")
            yield Button("Deny", variant="error", id="deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")
