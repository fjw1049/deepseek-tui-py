"""Sub-agent tools escalate to the parent approval bridge (three-tier dial)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.handle import DenyApprovalHandler
from deepseek_tui.policy.approval import ApprovalDecision
from deepseek_tui.tools.file import WriteFileTool
from deepseek_tui.tools.registry import ToolRegistry, ToolResult
from deepseek_tui.tools.shell import ExecShellTool
from deepseek_tui.tools.subagent.loop import _execute_subagent_tool


class _RecordingHandler(DenyApprovalHandler):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def request_approval(self, tool_call_id: str, request: object) -> ApprovalDecision:
        self.calls.append(getattr(request, "tool_name", ""))
        return ApprovalDecision.APPROVED


def _registry(*tools: object) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)  # type: ignore[arg-type]
    registry.execute = AsyncMock(  # type: ignore[method-assign]
        return_value=ToolResult(success=True, content="ok")
    )
    return registry


@pytest.mark.asyncio
async def test_untrusted_allows_write_without_parent_prompt() -> None:
    registry = _registry(WriteFileTool())
    handler = _RecordingHandler()
    emit = AsyncMock()
    runtime = SimpleNamespace(
        config=SimpleNamespace(approval_policy="untrusted"),
        approval_handler=handler,
        emit_event=emit,
    )
    out = await _execute_subagent_tool(
        registry,
        SimpleNamespace(metadata={}),
        tool_name="write_file",
        tool_input={"path": "a.py", "content": "x"},
        auto_approve=False,
        tool_call_id="tc-write",
        runtime=runtime,  # type: ignore[arg-type]
    )
    assert out == "ok"
    assert handler.calls == []
    emit.assert_not_called()
    registry.execute.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_untrusted_shell_escalates_to_parent_handler() -> None:
    registry = _registry(ExecShellTool())
    handler = _RecordingHandler()
    emit = AsyncMock()
    runtime = SimpleNamespace(
        config=SimpleNamespace(approval_policy="untrusted"),
        approval_handler=handler,
        emit_event=emit,
    )
    out = await _execute_subagent_tool(
        registry,
        SimpleNamespace(metadata={}),
        tool_name="exec_shell",
        tool_input={"command": "echo hi"},
        auto_approve=False,
        tool_call_id="tc-shell",
        runtime=runtime,  # type: ignore[arg-type]
    )
    assert out == "ok"
    assert handler.calls == ["exec_shell"]
    emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_approve_skips_parent_bridge() -> None:
    registry = _registry(ExecShellTool())
    handler = _RecordingHandler()
    runtime = SimpleNamespace(
        config=SimpleNamespace(approval_policy="on-request"),
        approval_handler=handler,
        emit_event=AsyncMock(),
    )
    out = await _execute_subagent_tool(
        registry,
        SimpleNamespace(metadata={}),
        tool_name="exec_shell",
        tool_input={"command": "echo hi"},
        auto_approve=True,
        tool_call_id="tc-auto",
        runtime=runtime,  # type: ignore[arg-type]
    )
    assert out == "ok"
    assert handler.calls == []


@pytest.mark.asyncio
async def test_denied_by_parent_returns_error() -> None:
    registry = _registry(ExecShellTool())
    runtime = SimpleNamespace(
        config=SimpleNamespace(approval_policy="on-request"),
        approval_handler=DenyApprovalHandler(),
        emit_event=AsyncMock(),
    )
    out = await _execute_subagent_tool(
        registry,
        SimpleNamespace(metadata={}),
        tool_name="exec_shell",
        tool_input={"command": "rm -rf /"},
        auto_approve=False,
        tool_call_id="tc-deny",
        runtime=runtime,  # type: ignore[arg-type]
    )
    assert out.startswith("Error:")
    assert "denied" in out.lower()
    registry.execute.assert_not_awaited()  # type: ignore[attr-defined]
