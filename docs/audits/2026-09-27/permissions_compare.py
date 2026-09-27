"""Compare existing main/child permission gates to a minimal deny-first rule.

No real tools execute. Run with PYTHONPATH=src .venv/bin/python <this file>.
The candidate is a decision-table prototype, not a production implementation.
"""
import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from deepseek_tui.engine.handle import ApprovalHandler
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.approval import (
    ApprovalCache, ApprovalDecision, GateAction, _gate_action,
    approval_request_for_tool, build_approval_key,
)
from deepseek_tui.tools.file import ReadFileTool, WriteFileTool
from deepseek_tui.tools.registry import ToolContext, ToolRegistry, ToolResult
from deepseek_tui.tools.shell import ExecShellTool
from deepseek_tui.tools.subagent.loop import _execute_subagent_tool


class Handler(ApprovalHandler):
    def __init__(self, auto, allow):
        self.auto, self.allow = auto, allow
    async def auto_approve_enabled(self):
        return self.auto
    async def request_approval(self, *_):
        return ApprovalDecision.APPROVED if self.auto or self.allow else ApprovalDecision.DENIED


def candidate(tool, policy, cached, auto, allow):
    action = _gate_action(tool.approval_requirement(), policy)
    if action is GateAction.BLOCK_NEVER:
        return False
    if action is GateAction.SKIP:
        return True
    return cached or auto or allow


async def case(root, label, tool, policy, cached, auto, allow):
    args = {"command": "echo probe"} if tool.name() == "exec_shell" else {"path": "note.txt", "content": "x"}
    call = ToolCall(id="probe", name=tool.name(), arguments=args)
    handler = Handler(auto, allow)
    gate = ToolExecutionMixin()
    gate.tool_context = ToolContext(working_directory=root)
    gate.approval_cache = ApprovalCache()
    gate.handle = SimpleNamespace(emit=AsyncMock())
    gate.approval_handler = handler
    if cached:
        gate.approval_cache.insert(build_approval_key(call.name, args, working_directory=root), True)
    req = approval_request_for_tool(tool, policy, args)
    main_allowed = True if req is None else not await gate._handle_approval_flow(call, req)
    registry = ToolRegistry()
    registry.register(tool)
    registry.execute = AsyncMock(return_value=ToolResult(success=True, content="mock"))
    await _execute_subagent_tool(registry, ToolContext(working_directory=root), tool_name=call.name,
        tool_input=args, auto_approve=auto, tool_call_id=call.id,
        runtime=SimpleNamespace(config=SimpleNamespace(approval_policy=policy),
                                approval_handler=handler, emit_event=AsyncMock()))
    return dict(case=label, main=main_allowed, child=bool(registry.execute.await_count),
                deny_first_candidate=candidate(tool, policy, cached, auto, allow))


async def main():
    scenarios = [
        ("never/read", ReadFileTool(), "never", False, False, True),
        ("never/write/manual-allow", WriteFileTool(), "never", False, False, True),
        ("never/write/auto", WriteFileTool(), "never", False, True, True),
        ("never/write/cached", WriteFileTool(), "never", True, False, False),
        ("on-request/shell/deny", ExecShellTool(), "on-request", False, False, False),
        ("on-request/shell/allow", ExecShellTool(), "on-request", False, False, True),
        ("on-request/shell/cached", ExecShellTool(), "on-request", True, False, False),
        ("untrusted/write", WriteFileTool(), "untrusted", False, False, False),
        ("auto/shell", ExecShellTool(), "auto", False, False, False),
    ]
    with tempfile.TemporaryDirectory(prefix="permission-compare-") as tmp, \
         patch("deepseek_tui.engine.orchestrator.tooling.emit_tool_audit"):
        rows = [await case(Path(tmp), *row) for row in scenarios]
    assert rows[1]["main"] is False and rows[1]["child"] is True
    assert rows[3]["main"] is True and rows[3]["deny_first_candidate"] is False
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
