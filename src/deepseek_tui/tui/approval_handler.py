"""TUI-backed approval handler — mirrors Rust ``tui/approval.rs``.

Stage 6.4: Bridges the engine's ``ApprovalHandler`` interface to the
Textual ``ApprovalDialog`` modal screen. When the engine requests
approval, this handler signals the TUI app to push the dialog and
awaits the user's response via an asyncio Future.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from deepseek_tui.engine.approval import ApprovalHandler
from deepseek_tui.execpolicy.models import ApprovalDecision, ApprovalRequest

if TYPE_CHECKING:
    from deepseek_tui.tui.app import DeepSeekTUI


class TUIApprovalHandler(ApprovalHandler):
    """Approval handler that shows a modal dialog in the TUI.

    The handler stores a reference to the Textual App so it can call
    ``push_screen`` from within the engine's async context.  The
    dialog result is communicated back via an ``asyncio.Future``.
    """

    def __init__(self, app: DeepSeekTUI) -> None:
        self._app = app

    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        from deepseek_tui.tui.widgets.approval import ApprovalDialog

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def _on_dismiss(result: bool | None) -> None:
            if not future.done():
                future.set_result(bool(result))

        dialog = ApprovalDialog(
            tool_name=request.tool_name,
            reason=request.reason,
        )
        self._app.push_screen(dialog, _on_dismiss)

        approved = await future
        if approved:
            return ApprovalDecision.APPROVED
        return ApprovalDecision.DENIED
