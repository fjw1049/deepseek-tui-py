"""Background task tool-approval bridge onto the origin thread."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deepseek_tui.engine.dispatch import (
    _build_task_approval_handler,
    bridge_background_approval,
)
from deepseek_tui.engine.events import ApprovalRequiredEvent
from deepseek_tui.engine.handle import AutoApprovalHandler, DenyApprovalHandler
from deepseek_tui.server.approval import ApprovalBridge, HttpApprovalHandler
from deepseek_tui.tools.approval import ApprovalDecision, ApprovalRequest, RiskLevel, ToolCategory
from deepseek_tui.tools.task.models import ExecutionTask


def _task(**kwargs: Any) -> ExecutionTask:
    base = dict(
        id="task_1",
        prompt="write a file",
        model="deepseek-chat",
        workspace="/tmp",
        mode_label="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=False,
        thread_id="thread_1",
    )
    base.update(kwargs)
    return ExecutionTask(**base)


def _approval_request() -> ApprovalRequest:
    return ApprovalRequest(
        tool_name="write_file",
        risk_level=RiskLevel.MEDIUM,
        category=ToolCategory.FILE_WRITE,
        reason="Write heap_sort_result.txt",
        title="Write file",
        input_summary="heap_sort_result.txt",
        presentation_risk="benign",
        approval_key="write_file:heap_sort_result.txt",
    )


def test_build_handler_auto_approve() -> None:
    handler = _build_task_approval_handler(_task(auto_approve=True))
    assert isinstance(handler, AutoApprovalHandler)


def test_build_handler_denies_without_bridge() -> None:
    handler = _build_task_approval_handler(_task(auto_approve=False))
    assert isinstance(handler, DenyApprovalHandler)


def test_build_handler_bridges_to_origin() -> None:
    bridge = ApprovalBridge()
    mgr = SimpleNamespace(approval_bridge=bridge, thread_manager=object())
    handler = _build_task_approval_handler(
        _task(auto_approve=False, task_manager=mgr)
    )
    assert isinstance(handler, HttpApprovalHandler)
    assert handler._thread_id == "thread_1"
    assert handler._task_id == "task_1"


@pytest.mark.asyncio
async def test_bridge_emits_approval_on_origin_thread() -> None:
    emitted: list[dict[str, Any]] = []

    class FakeThreadManager:
        async def emit_bridged_approval(
            self,
            thread_id: str,
            approval_id: str,
            request: Any,
            *,
            task_id: str | None = None,
        ) -> None:
            emitted.append(
                {
                    "thread_id": thread_id,
                    "approval_id": approval_id,
                    "tool_name": request.tool_name,
                    "task_id": task_id,
                }
            )

    mgr = SimpleNamespace(thread_manager=FakeThreadManager())
    event = ApprovalRequiredEvent(
        tool_call_id="call_write",
        request=_approval_request(),
    )
    await bridge_background_approval(event, task=_task(task_manager=mgr))
    assert emitted == [
        {
            "thread_id": "thread_1",
            "approval_id": "call_write",
            "tool_name": "write_file",
            "task_id": "task_1",
        }
    ]


@pytest.mark.asyncio
async def test_bridge_noop_without_origin_thread() -> None:
    emitted: list[str] = []

    class FakeThreadManager:
        async def emit_bridged_approval(self, *args: Any, **kwargs: Any) -> None:
            emitted.append("called")

    mgr = SimpleNamespace(thread_manager=FakeThreadManager())
    event = ApprovalRequiredEvent(
        tool_call_id="call_write",
        request=_approval_request(),
    )
    await bridge_background_approval(
        event, task=_task(thread_id=None, task_manager=mgr)
    )
    assert emitted == []


@pytest.mark.asyncio
async def test_http_handler_registers_task_id() -> None:
    bridge = ApprovalBridge()
    handler = HttpApprovalHandler(
        bridge, thread_id="thread_1", task_id="task_9"
    )
    req = _approval_request()
    # Kick request_approval without awaiting completion.
    import asyncio

    task = asyncio.create_task(handler.request_approval("appr_1", req))
    await asyncio.sleep(0)
    pending = bridge.list_pending(thread_id="thread_1")
    assert len(pending) == 1
    assert pending[0]["task_id"] == "task_9"
    assert bridge.resolve("appr_1", True)
    assert await task == ApprovalDecision.APPROVED
