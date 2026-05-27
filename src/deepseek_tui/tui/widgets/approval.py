"""Approval modal — surfaces impacts and command preview before approval."""
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
        max-height: 12;
    }
    ApprovalDialog #approval-confirm {
        margin: 1 0;
        color: $warning;
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
        *,
        title: str = "",
        impacts: list[str] | None = None,
        presentation_risk: str = "",
        primary_preview: str = "",
    ) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.reason = reason
        self.title = title or reason
        self.impacts = impacts or []
        self.presentation_risk = presentation_risk
        preview = (primary_preview or input_summary or "").strip()
        self.input_summary = preview
        self.risk_level = risk_level
        self._pending_confirm = False

    def _is_destructive(self) -> bool:
        return self.presentation_risk == "destructive"

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-box"):
            header = "[bold]Approve tool call?[/]"
            if self._is_destructive():
                header = "[bold yellow]Review required[/]"
            yield Label(header)
            if self.title and self.title != self.reason:
                yield Label(f"[dim]Summary:[/] {escape(self.title)}")
            yield Label(f"[dim]Tool:[/]    [bold]{escape(self.tool_name)}[/]")
            if self.risk_level:
                yield Label(f"[dim]Risk:[/]    [yellow]{escape(self.risk_level)}[/]")
            for line in self.impacts[:8]:
                yield Label(f"  • {escape(line)}")
            if self.reason and not self.reason.startswith("tool has "):
                yield Label(f"[dim]Note:[/]    {escape(self.reason)}")
            if self.input_summary:
                yield Label("[dim]Preview:[/]")
                yield Static(escape(self.input_summary), id="approval-cmd")
            yield Label("", id="approval-confirm")
            with Horizontal(id="approval-buttons"):
                yield Button(
                    "Approve  (Enter / y)", variant="success", id="approve"
                )
                yield Button("Deny  (Esc / n)", variant="error", id="deny")

    def on_mount(self) -> None:
        self._sync_confirm_banner()

    def _sync_confirm_banner(self) -> None:
        try:
            banner = self.query_one("#approval-confirm", Label)
        except Exception:  # noqa: BLE001
            return
        if self._pending_confirm and self._is_destructive():
            banner.update(
                "[bold yellow]Confirm destructive action — press Approve again[/]"
            )
        else:
            banner.update("")

    def _try_approve(self) -> None:
        if self._is_destructive() and not self._pending_confirm:
            self._pending_confirm = True
            self._sync_confirm_banner()
            return
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approve":
            self._try_approve()
        else:
            self._pending_confirm = False
            self.dismiss(False)

    def action_approve(self) -> None:
        self._try_approve()

    def action_deny(self) -> None:
        self._pending_confirm = False
        self.dismiss(False)
