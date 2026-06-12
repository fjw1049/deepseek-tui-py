"""HttpApprovalHandler blocks Engine until ApprovalBridge resolves."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.server.approval import (
    ApprovalBridge,
    HttpApprovalHandler,
)
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.policy.approval import (
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

    assert await handler.auto_approve_enabled() is True

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


@pytest.mark.asyncio
async def test_http_auto_approve_reaches_subagent_runtime(tmp_path) -> None:
    bridge = ApprovalBridge()

    async def always_yes() -> bool:
        return True

    handler = HttpApprovalHandler(bridge, auto_approve=always_yes)
    engine = await Engine.create(
        handle=EngineHandle(),
        client=AsyncMock(),
        config=Config(
            features=FeatureConfig(
                tasks=False,
                subagents=True,
                mcp=False,
                automations=False,
            )
        ),
        working_directory=tmp_path,
        approval_handler=handler,
    )
    try:
        assert engine.tool_runtime is not None
        assert engine.tool_runtime.subagent_manager is not None
        loop_runtime = engine.tool_runtime.subagent_manager.loop_runtime
        assert loop_runtime is not None
        assert loop_runtime.auto_approve is True
    finally:
        await engine.shutdown_session()
