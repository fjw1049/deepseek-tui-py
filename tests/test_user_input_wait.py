"""Waiting on the person: browser takeover and plain questions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.user_input import validate_user_input_request


@pytest.fixture
def context(tmp_path):
    run = SimpleNamespace(owner="agent", assistance=None, unresolved={})
    return ToolContext(
        working_directory=tmp_path,
        metadata={
            "browser_service": SimpleNamespace(runs={"t": run}),
            "runtime_thread_id": "t",
        },
    )








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










