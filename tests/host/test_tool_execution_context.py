"""Tests for typed per-tool execution context bindings."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deepseek_tui.capabilities.rlm import execute_rlm_tool, rlm_tool_bindings
from deepseek_tui.capabilities.workflow import workflow_tool_bindings
from deepseek_tui.host.tool_execution import (
    RlmToolExecution,
    WorkflowToolExecution,
    resolve_rlm_progress_cb,
    resolve_workflow_emit,
    resolve_workflow_tool_call_id,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.rlm.turn import RlmTermination, RlmTurnResult, RlmUsage


def test_workflow_bindings_set_and_clear_typed_context(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    with workflow_tool_bindings(
        context,
        cancel_event=asyncio.Event(),
        tool_call_id="tool-typed",
        emit=lambda _event: True,
    ):
        assert context.tool_execution is not None
        assert isinstance(context.tool_execution.workflow, WorkflowToolExecution)
        assert context.tool_execution.workflow.tool_call_id == "tool-typed"
        assert resolve_workflow_tool_call_id(context) == "tool-typed"
        assert resolve_workflow_emit(context) is not None

    assert context.tool_execution is None


def test_rlm_bindings_set_and_clear_typed_context(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    with rlm_tool_bindings(context, emit=lambda _event: True):
        assert context.tool_execution is not None
        assert isinstance(context.tool_execution.rlm, RlmToolExecution)
        assert resolve_rlm_progress_cb(context) is not None

    assert context.tool_execution is None


def test_workflow_and_rlm_bindings_can_coexist(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    with workflow_tool_bindings(
        context,
        cancel_event=asyncio.Event(),
        tool_call_id="tool-1",
        emit=lambda _event: True,
    ):
        with rlm_tool_bindings(context, emit=lambda _event: True):
            assert context.tool_execution is not None
            assert context.tool_execution.workflow is not None
            assert context.tool_execution.rlm is not None

        assert context.tool_execution is not None
        assert context.tool_execution.workflow is not None
        assert context.tool_execution.rlm is None

    assert context.tool_execution is None


def test_resolve_helpers_require_typed_context(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    assert resolve_workflow_tool_call_id(context) == ""


@pytest.mark.asyncio
async def test_rlm_execute_uses_typed_progress_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[object] = []

    async def _fake_run_rlm_turn(**kwargs: object) -> RlmTurnResult:
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            on_progress(3, "typed progress", 1)
        return RlmTurnResult(
            answer="ok",
            iterations=1,
            duration_secs=0.01,
            error=None,
            termination=RlmTermination.FINAL,
            total_rpcs=0,
            usage=RlmUsage(),
            trace=[],
        )

    monkeypatch.setattr(
        "deepseek_tui.capabilities.rlm.run_rlm_turn",
        _fake_run_rlm_turn,
    )
    context = ToolContext(working_directory=tmp_path)

    with rlm_tool_bindings(context, emit=lambda event: not emitted.append(event)):
        result = await execute_rlm_tool(
            client=object(),  # type: ignore[arg-type]
            root_model="deepseek-chat",
            input_data={"task": "summarize", "content": "hello"},
            context=context,
        )
        assert context.tool_execution is not None

    assert result.success is True
    assert len(emitted) == 1
    assert emitted[0].iteration == 3
    assert emitted[0].summary == "typed progress"
    assert emitted[0].rpc_count == 1
    assert context.tool_execution is None
