"""HttpApprovalHandler blocks Engine until ApprovalBridge resolves."""

from __future__ import annotations

import asyncio

import pytest

from deepseek_tui.app_server.runtime_api.approval_bridge import (
    ApprovalBridge,
    HttpApprovalHandler,
)
from deepseek_tui.execpolicy.models import (
    ApprovalDecision,
    ApprovalRequest,
    RiskLevel,
    ToolCategory,
)


@pytest.mark.asyncio
async def test_http_approval_handler_blocks_until_bridge_allow() -> None:
    bridge = ApprovalBridge()
    handler = HttpApprovalHandler(bridge)

    async def resolve_later() -> None:
        await asyncio.sleep(0.02)
        assert bridge.resolve("appr_1", True)

    asyncio.create_task(resolve_later())
    decision = await handler.request_approval(
        "appr_1",
        ApprovalRequest(
            tool_name="write_file",
            risk_level=RiskLevel.MEDIUM,
            category=ToolCategory.FILE_WRITE,
            reason="write test.txt",
        ),
    )
    assert decision is ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_http_approval_handler_auto_approve_skips_bridge() -> None:
    bridge = ApprovalBridge()

    async def always_yes() -> bool:
        return True

    handler = HttpApprovalHandler(bridge, auto_approve=always_yes)

    decision = await handler.request_approval(
        "appr_auto",
        ApprovalRequest(
            tool_name="bash",
            risk_level=RiskLevel.MEDIUM,
            category=ToolCategory.CODE_EXEC,
            reason="run ls",
        ),
    )
    assert decision is ApprovalDecision.APPROVED
    assert "appr_auto" not in bridge._pending
