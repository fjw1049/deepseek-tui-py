"""Approval modal — surfaces the actual command being approved.

The previous version showed only ``tool_name`` and a generic ``reason``
("tool has medium risk level"), forcing the user to approve blindly.
This version renders ``ApprovalRequest.input_summary`` as a clearly
demarcated command/args block plus tool metadata, and binds keyboard
shortcuts (Enter to approve, Esc to deny) so the flow stays fast.
"""
from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ApprovalDialog(ModalScreen[bool]):
    """Modal dialog for tool execution approval."""

    CSS = """
    ApprovalDialog {
        align: center middle;
    }
    ApprovalDialog #approval-box {
        width: 80;
        max-width: 90%;
        height: auto;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    ApprovalDialog #approval-cmd {
        margin: 1 0;
        padding: 0 1;
        background: $boost;
        color: $text;
        border: round $primary;
        height: auto;
        max-height: 10;
    }
    ApprovalDialog #approval-buttons {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    ApprovalDialog #approval-buttons > Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("enter", "approve", "Approve", show=False),
        Binding("escape", "deny", "Deny", show=False),
        Binding("y", "approve", "Approve", show=False),
        Binding("n", "deny", "Deny", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        reason: str,
        input_summary: str = "",
        risk_level: str = "",
    ) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.reason = reason
        self.input_summary = input_summary
        self.risk_level = risk_level

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-box"):
            yield Label("[bold]Approve tool call?[/]")
            yield Label(
                f"[dim]Tool:[/]    [bold]{escape(self.tool_name)}[/]"
            )
            if self.risk_level:
                yield Label(
                    f"[dim]Risk:[/]    [yellow]{escape(self.risk_level)}[/]"
                )
            if self.reason:
                yield Label(f"[dim]Reason:[/]  {escape(self.reason)}")
            if self.input_summary:
                yield Label("[dim]Command:[/]")
                yield Static(escape(self.input_summary), id="approval-cmd")
            with Horizontal(id="approval-buttons"):
                yield Button(
                    "Approve  (Enter / y)", variant="success", id="approve"
                )
                yield Button("Deny  (Esc / n)", variant="error", id="deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)
