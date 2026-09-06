import asyncio
from types import SimpleNamespace

import pytest

from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.approval import ApprovalBridge, HttpApprovalHandler
from deepseek_tui.tools.approval import (
    ApprovalCache,
    ApprovalDecision,
    ApprovalRequest,
    RiskLevel,
    ToolCategory,
)
from deepseek_tui.tools.registry import ToolContext


def request():
    return ApprovalRequest(
        tool_name="exec_shell",
        risk_level=RiskLevel.MEDIUM,
        category=ToolCategory.CODE_EXEC,
        reason="Run command",
    )


async def test_same_tool_call_in_two_threads_has_independent_approvals():
    bridge = ApprovalBridge()
    requests = [request(), request()]
    handlers = [HttpApprovalHandler(bridge, thread_id=name) for name in ("a", "b")]
    tasks = [
        asyncio.create_task(h.request_approval("same-call", r))
        for h, r in zip(handlers, requests, strict=True)
    ]
    try:
        await asyncio.sleep(0)
        pending = bridge.list_pending()
        assert len(pending) == 2
        ids = {row["thread_id"]: row["approval_id"] for row in pending}
        assert len(set(ids.values())) == 2
        assert "same-call" not in ids.values()
        assert all(row["tool_call_id"] == "same-call" for row in pending)
        assert bridge.resolve(ids["a"], True, remember=True)
        assert await asyncio.wait_for(tasks[0], 1) is ApprovalDecision.APPROVED_SESSION
        assert not tasks[1].done()
        assert bridge.resolve(ids["b"], False)
        assert await asyncio.wait_for(tasks[1], 1) is ApprovalDecision.DENIED
        assert not bridge.resolve(ids["a"], True)
        assert not bridge._pending and not bridge._meta and not bridge._remember
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_duplicate_bridge_registration_never_overwrites_waiter():
    bridge = ApprovalBridge()
    first = bridge.register("duplicate")
    try:
        with pytest.raises(ValueError):
            bridge.register("duplicate")
        assert bridge.resolve("duplicate", True)
        assert await first is True
    finally:
        first.cancel()
        bridge.cancel_all()


async def test_cancelled_request_cleans_records_and_propagates_cancel():
    bridge = ApprovalBridge()
    task = asyncio.create_task(HttpApprovalHandler(bridge).request_approval("call", request()))
    await asyncio.sleep(0)
    old_id = bridge.list_pending()[0]["approval_id"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not bridge._pending and not bridge._meta and not bridge._remember
    assert not bridge.resolve(old_id, True, remember=True)


@pytest.mark.parametrize("event_fails", [False, True])
async def test_gate_registers_before_card_and_cleans_up_on_emit_failure(tmp_path, event_fails):
    bridge = ApprovalBridge()
    gate = ToolExecutionMixin()
    gate.approval_handler = HttpApprovalHandler(bridge, thread_id="thread")
    gate.approval_cache = ApprovalCache()
    gate.tool_context = ToolContext(working_directory=tmp_path)

    async def emit(event):
        from deepseek_tui.engine.events import ApprovalRequiredEvent

        if isinstance(event, ApprovalRequiredEvent):
            pending = bridge.list_pending()
            assert len(pending) == 1
            assert pending[0]["approval_id"] == event.request.approval_id
            if event_fails:
                raise RuntimeError("event delivery failed")
            assert bridge.resolve(event.request.approval_id, True)

    gate.handle = SimpleNamespace(emit=emit)
    call = ToolCall(id="call", name="exec_shell", arguments={"command": "echo hi"})
    if event_fails:
        with pytest.raises(RuntimeError, match="event delivery failed"):
            await gate._handle_approval_flow(call, request())
    else:
        assert await asyncio.wait_for(gate._handle_approval_flow(call, request()), 1) is False
    assert not bridge._pending and not bridge._meta and not bridge._remember


async def test_turn_cleanup_keeps_other_turn_and_detached_task():
    bridge = ApprovalBridge()
    handlers = [
        HttpApprovalHandler(bridge, thread_id="thread", get_turn_id=lambda: "old"),
        HttpApprovalHandler(bridge, thread_id="thread", get_turn_id=lambda: "new"),
        HttpApprovalHandler(bridge, thread_id="thread", task_id="detached"),
    ]
    tasks = [asyncio.create_task(h.request_approval("same", request())) for h in handlers]
    try:
        await asyncio.sleep(0)
        bridge.cancel_for_turn("thread", "old")
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        assert len(bridge.list_pending()) == 2
        assert not tasks[1].done() and not tasks[2].done()
        bridge.cancel_for_thread("thread", include_tasks=False)
        with pytest.raises(asyncio.CancelledError):
            await tasks[1]
        assert len(bridge.list_pending()) == 1
        assert bridge.list_pending()[0]["task_id"] == "detached"
        assert not tasks[2].done()
        bridge.cancel_for_thread("thread")
        await asyncio.gather(*tasks, return_exceptions=True)
        assert not bridge._pending and not bridge._meta and not bridge._remember
    finally:
        bridge.cancel_all()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_old_answer_does_not_affect_reused_tool_call():
    bridge = ApprovalBridge()
    handler = HttpApprovalHandler(bridge, thread_id="thread")
    first = asyncio.create_task(handler.request_approval("reused", request()))
    await asyncio.sleep(0)
    old_id = bridge.list_pending()[0]["approval_id"]
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    second = asyncio.create_task(handler.request_approval("reused", request()))
    try:
        await asyncio.sleep(0)
        new_id = bridge.list_pending()[0]["approval_id"]
        assert new_id != old_id
        assert not bridge.resolve(old_id, True, remember=True)
        assert not second.done()
        assert bridge.resolve(new_id, True, remember=True)
        # A duplicated browser response must not erase the remembered grant.
        assert not bridge.resolve(new_id, True)
        assert await second is ApprovalDecision.APPROVED_SESSION
    finally:
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
