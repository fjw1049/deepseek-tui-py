"""Task focus cannot expand authorization or mistake an unknown mutation for success."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.task_delivery import FinishTaskTool, RequestTaskToolsTool, TaskDelivery
from deepseek_tui.tools.user_input import validate_user_input_request


@pytest.fixture
def context(tmp_path):
    state = TaskDelivery(active=True, focused=True, browser_used=True,
                         catalog={"browser_use", "read_file"},
                         evidence={"tool:read"})
    run = SimpleNamespace(owner="agent", assistance=None, unresolved={})
    return ToolContext(
        working_directory=tmp_path,
        metadata={
            "task_delivery": state,
            "browser_service": SimpleNamespace(runs={"t": run}),
            "runtime_thread_id": "t",
        },
    )


@pytest.mark.parametrize(
    "change,error",
    [
        ({"evidence": ["tool:invented"]}, "Unknown evidence"),
        ({"evidence": []}, "requires evidence"),
        ({"remaining": ["download invoice"]}, "no remaining"),
        ({"status": "blocked", "remaining": []}, "concrete remaining"),
        ({"answer": " "}, "non-empty actual answer"),
    ],
)
async def test_delivery_validation(context, change, error):
    args = dict(
        status="completed", answer="Order 123 is delivered", evidence=["tool:read"], remaining=[]
    )
    with pytest.raises(ToolError, match=error):
        await FinishTaskTool().execute({**args, **change}, context)
    assert context.metadata["task_delivery"].outcome is None


async def test_unknown_mutation_requires_partial_delivery(context):
    run = context.metadata["browser_service"].runs["t"]
    run.unresolved = {"submit": {"effect": "unknown"}}
    args = dict(status="completed", answer="Submitted", evidence=["tool:read"], remaining=[])
    with pytest.raises(ToolError, match="Unresolved"):
        await FinishTaskTool().execute(args, context)
    result = await FinishTaskTool().execute(
        {
            **args,
            "status": "partial",
            "answer": "Submission status is unknown",
            "remaining": ["Verify order 123"],
        },
        context,
    )
    assert result.success
    assert context.metadata["task_delivery"].outcome["status"] == "partial"


async def test_focus_extension_is_named_and_bounded_by_catalog(context):
    state = context.metadata["task_delivery"]
    assert state.allows("read_file")
    with pytest.raises(ToolError, match="unavailable"):
        await RequestTaskToolsTool().execute(
            {"names": ["read_file", "exec_shell"], "reason": "analyze"}, context
        )
    assert not state.extra_tools
    await RequestTaskToolsTool().execute(
        {"names": ["read_file"], "reason": "Read downloaded invoice"}, context
    )
    assert state.allows("read_file") and state.allows("exec_shell")


def test_browser_phase_keeps_computer_use_available(context):
    # A web-to-desktop task must not have to request its own desktop surface.
    state = context.metadata["task_delivery"]
    assert state.allows("cua_js") and state.allows("cua_js_reset")
    assert state.allows("exec_shell")
    assert not state.allows("write_file")


def test_free_text_question_and_invalid_single_choice():
    question = {"header": "Order", "id": "order", "question": "What is the order number?"}
    assert validate_user_input_request({"questions": [question]})[0].options == []
    with pytest.raises(ToolError, match="2-4"):
        validate_user_input_request({"questions": [{**question, "options": [{"label": "fake"}]}]})


async def test_action_uses_only_takeover_wait(context):
    request = AsyncMock(return_value={"success": True, "content": "Paused"})
    context.metadata["request_browser_assistance"] = request
    engine = SimpleNamespace(
        tool_context=context, mode="agent", handle=EngineHandle(), _release_cua=AsyncMock()
    )
    result = await ToolExecutionMixin._await_user_input(
        engine,
        "ask",
        {
            "kind": "action",
            "surface": "browser",
            "reason": "Please log in",
        },
    )
    assert result.success
    request.assert_awaited_once_with("t", "Please log in")
    assert not engine.handle.pending_user_inputs


async def test_information_wait_needs_no_browser(context):
    engine = SimpleNamespace(
        tool_context=context, mode="agent", handle=EngineHandle(), _release_cua=AsyncMock()
    )
    engine._await_user_input_raw = lambda *a, **kw: ToolExecutionMixin._await_user_input_raw(
        engine, *a, **kw
    )
    context.metadata.pop("browser_service")
    task = asyncio.create_task(
        ToolExecutionMixin._await_user_input(
            engine,
            "ask",
            {
                "kind": "information",
                "questions": [{"header": "Order", "id": "order", "question": "Order number?"}],
            },
        )
    )
    try:
        await asyncio.sleep(0)
        assert not engine.handle.pause.paused
        engine.handle.pending_user_inputs["ask"].set_result({"answers": {"order": "123"}})
        assert (await asyncio.wait_for(task, 1)).success
        assert not engine.handle.pending_user_inputs
        # The desktop is never held while a person is being asked.
        engine._release_cua.assert_awaited_once_with(reset=True)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_closed_session_does_not_erase_unknown_mutation(context):
    context.metadata["browser_service"] = SimpleNamespace(
        runs={}, state=lambda _: {"unresolved": [{"action_id": "old-submit"}]}
    )
    with pytest.raises(ToolError, match="Unresolved"):
        await FinishTaskTool().execute(dict(
            status="completed", answer="Submitted", evidence=["tool:read"], remaining=[]
        ), context)


@pytest.mark.parametrize("pending", ["dialog", "file_chooser", "pending_action", "pending_input"])
async def test_pending_browser_interaction_prevents_completion(context, pending):
    browser = context.metadata["browser_service"]
    browser.state = lambda _: (
        {pending: {"id": "pending"}} if pending in {"dialog", "file_chooser"} else {}
    )
    if pending.startswith("pending_"):
        setattr(browser.runs["t"], pending, object())
    args = dict(status="completed", answer="Submitted", evidence=["tool:read"], remaining=[])
    with pytest.raises(ToolError, match="pending browser"):
        await FinishTaskTool().execute(args, context)
    assert (
        await FinishTaskTool().execute(
            {**args, "status": "blocked", "remaining": ["Handle pending interaction"]}, context
        )
    ).success


async def test_desktop_only_delivery_ignores_unrelated_browser_control(context):
    state = context.metadata["task_delivery"]
    state.browser_used = False
    run = context.metadata["browser_service"].runs["t"]
    run.owner = "user"
    run.unresolved = {"old-submit": {"effect": "unknown"}}
    result = await FinishTaskTool().execute(dict(
        status="completed", answer="Read the local document", evidence=["tool:read"], remaining=[]
    ), context)
    assert result.success


async def test_agent_closing_its_browser_session_can_still_complete(context):
    # close_session leaves owner "stopped"; nobody holds the browser, so the
    # agent's evidence still stands. A user stop cancels the turn before this.
    context.metadata["browser_service"].runs["t"].owner = "stopped"
    result = await FinishTaskTool().execute(dict(
        status="completed", answer="Reviewed the page", evidence=["tool:read"], remaining=[]
    ), context)
    assert result.success


async def test_mixed_task_still_requires_browser_control(context):
    context.metadata["browser_service"].runs["t"].owner = "user"
    with pytest.raises(ToolError, match="user controls the browser"):
        await FinishTaskTool().execute(dict(
            status="completed", answer="Read both", evidence=["tool:read"], remaining=[]
        ), context)
