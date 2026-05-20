from __future__ import annotations

from deepseek_tui.execpolicy.models import ApprovalDecision, ApprovalRequest


class ApprovalHandler:
    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        raise NotImplementedError


class AutoApprovalHandler(ApprovalHandler):
    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        return ApprovalDecision.APPROVED


class DenyApprovalHandler(ApprovalHandler):
    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        return ApprovalDecision.DENIED
