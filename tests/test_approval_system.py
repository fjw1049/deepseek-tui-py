"""Unified approval system tests — gate + presentation + bridge + SSE."""

from __future__ import annotations

import asyncio

import pytest

from deepseek_tui.server.approval import (
    ApprovalBridge,
    HttpApprovalHandler,
    PendingApprovalRecord,
)
from deepseek_tui.policy.approval import ApprovalDecision, ApprovalRequest, RiskLevel, ToolCategory
from deepseek_tui.tools.approval import (
    approval_request_for_tool,
    needs_tool_approval_prompt,
)
from deepseek_tui.tools.approval import (
    approval_request_to_sse_payload,
    enrich_approval_request,
)
from deepseek_tui.tools.file import WriteFileTool
from deepseek_tui.tools.web import FetchUrlTool


def test_unified_write_file_gate_prompt_and_sse() -> None:
    tool = WriteFileTool()
    assert needs_tool_approval_prompt(tool, "on-request")
    req = approval_request_for_tool(tool, "on-request")
    assert req is not None
    enrich_approval_request(
        req,
        "write_file",
        {"path": "src/a.py", "content": "x"},
        tool_description=tool.description(),
    )
    assert req.title
    assert req.impacts
    assert req.presentation_risk == "destructive"
    assert "medium risk" not in req.title

    payload = approval_request_to_sse_payload("tc-unified-1", req)
    assert payload["tool_name"] == "write_file"
    assert isinstance(payload["impacts"], list)
    assert len(payload["impacts"]) >= 1
    assert payload["risk"] == "destructive"
    assert payload["input_summary"]


def test_unified_fetch_url_gated_on_request() -> None:
    tool = FetchUrlTool()
    assert needs_tool_approval_prompt(tool, "on-request")
    assert approval_request_for_tool(tool, "auto") is None


@pytest.mark.asyncio
async def test_unified_bridge_pending_carries_impacts() -> None:
    bridge = ApprovalBridge()
    req = ApprovalRequest(
        tool_name="exec_shell",
        risk_level=RiskLevel.MEDIUM,
        category=ToolCategory.CODE_EXEC,
        reason="Run command",
    )
    enrich_approval_request(
        req,
        "exec_shell",
        {"command": "npm test", "cwd": "/tmp/ws"},
    )
    handler = HttpApprovalHandler(bridge, thread_id="thr_unified")

    async def wait_decision() -> ApprovalDecision:
        return await handler.request_approval("appr-unified-bridge", req)

    task = asyncio.create_task(wait_decision())
    await asyncio.sleep(0.01)

    pending = bridge.list_pending(thread_id="thr_unified")
    assert len(pending) == 1
    row = pending[0]
    assert row["tool_name"] == "exec_shell"
    assert isinstance(row["impacts"], list)
    assert any("npm test" in str(line) for line in row["impacts"])  # type: ignore[arg-type]
    assert row["risk"] == "destructive"

    assert bridge.resolve("appr-unified-bridge", True)
    assert await task is ApprovalDecision.APPROVED


def test_tui_dialog_destructive_stages_before_dismiss() -> None:
    from deepseek_tui.tui.dialogs import ApprovalDialog

    dialog = ApprovalDialog(
        "write_file",
        "Write file",
        presentation_risk="destructive",
        impacts=["Writes: a.py"],
    )
    assert dialog._is_destructive()
    dialog._try_approve()
    assert dialog._pending_confirm


def test_unified_never_blocks_without_prompt() -> None:
    tool = WriteFileTool()
    req = approval_request_for_tool(tool, "never")
    assert req is not None
    assert "never" in req.reason
    assert not needs_tool_approval_prompt(tool, "never")
