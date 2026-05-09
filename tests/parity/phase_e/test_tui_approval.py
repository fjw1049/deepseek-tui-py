"""Stage 6.4 parity tests: TUI Approval Handler.

Verifies that TUIApprovalHandler can bridge engine approval requests
to UI, and that ApprovalDialog produces correct results.
"""
from __future__ import annotations

from deepseek_tui.engine.approval import AutoApprovalHandler, DenyApprovalHandler
from deepseek_tui.execpolicy.models import (
    ApprovalDecision,
    ApprovalRequest,
    RiskLevel,
    ToolCategory,
)
from deepseek_tui.tui.approval_handler import TUIApprovalHandler
from deepseek_tui.tui.widgets.approval import ApprovalDialog


def _make_request(
    tool_name: str = "exec_shell", reason: str = "test"
) -> ApprovalRequest:
    return ApprovalRequest(
        tool_name=tool_name,
        risk_level=RiskLevel.HIGH,
        category=ToolCategory.CODE_EXEC,
        reason=reason,
    )


class TestApprovalDialog:
    def test_dialog_construction(self) -> None:
        dialog = ApprovalDialog(tool_name="exec_shell", reason="dangerous")
        assert dialog.tool_name == "exec_shell"
        assert dialog.reason == "dangerous"

    def test_dialog_is_modal_screen(self) -> None:
        from textual.screen import ModalScreen
        dialog = ApprovalDialog(tool_name="test", reason="r")
        assert isinstance(dialog, ModalScreen)


class TestTUIApprovalHandler:
    def test_handler_construction(self) -> None:
        handler = TUIApprovalHandler(app=None)  # type: ignore[arg-type]
        assert handler._app is None

    def test_handler_is_approval_handler(self) -> None:
        from deepseek_tui.engine.approval import ApprovalHandler
        handler = TUIApprovalHandler(app=None)  # type: ignore[arg-type]
        assert isinstance(handler, ApprovalHandler)


class TestAutoApprovalHandler:
    async def test_auto_always_approves(self) -> None:
        handler = AutoApprovalHandler()
        result = await handler.request_approval("tc-1", _make_request())
        assert result is ApprovalDecision.APPROVED


class TestDenyApprovalHandler:
    async def test_deny_always_denies(self) -> None:
        handler = DenyApprovalHandler()
        result = await handler.request_approval("tc-1", _make_request())
        assert result is ApprovalDecision.DENIED
