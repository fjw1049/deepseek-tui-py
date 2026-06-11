"""Short-lived per-tool execution bindings for dynamic callbacks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.tools.context import ToolContext

logger = logging.getLogger(__name__)

EmitFn = Callable[[object], bool]
WorkflowProgressFn = Callable[[object], None]
WorkflowStatusFn = Callable[[str], None]
RlmProgressFn = Callable[[int, str, int], None]


@dataclass(slots=True)
class WorkflowToolExecution:
    cancel_event: object | None = None
    tool_call_id: str = ""
    emit_progress: WorkflowProgressFn | None = None
    emit_status: WorkflowStatusFn | None = None


@dataclass(slots=True)
class RlmToolExecution:
    on_progress: RlmProgressFn | None = None


@dataclass(slots=True)
class ToolExecutionContext:
    workflow: WorkflowToolExecution | None = None
    rlm: RlmToolExecution | None = None


def clear_tool_execution_if_empty(context: ToolContext) -> None:
    exec_ctx = context.tool_execution
    if exec_ctx is None:
        return
    if exec_ctx.workflow is None and exec_ctx.rlm is None:
        context.tool_execution = None


def ensure_tool_execution(context: ToolContext) -> ToolExecutionContext:
    exec_ctx = context.tool_execution
    if exec_ctx is None:
        exec_ctx = ToolExecutionContext()
        context.tool_execution = exec_ctx
    return exec_ctx


def resolve_workflow_cancel_event(context: ToolContext) -> asyncio.Event:
    exec_ctx = context.tool_execution
    if exec_ctx is not None and exec_ctx.workflow is not None:
        cancel_event = exec_ctx.workflow.cancel_event
        if isinstance(cancel_event, asyncio.Event):
            return cancel_event
    return asyncio.Event()


def resolve_workflow_tool_call_id(context: ToolContext) -> str:
    exec_ctx = context.tool_execution
    if exec_ctx is not None and exec_ctx.workflow is not None:
        tool_call_id = exec_ctx.workflow.tool_call_id
        if isinstance(tool_call_id, str):
            return tool_call_id
    return ""


def resolve_workflow_emit(context: ToolContext) -> WorkflowProgressFn | None:
    exec_ctx = context.tool_execution
    if exec_ctx is not None and exec_ctx.workflow is not None:
        emit = exec_ctx.workflow.emit_progress
        if callable(emit):
            return emit
    return None


def resolve_workflow_status_cb(context: ToolContext) -> WorkflowStatusFn | None:
    exec_ctx = context.tool_execution
    if exec_ctx is not None and exec_ctx.workflow is not None:
        status_cb = exec_ctx.workflow.emit_status
        if callable(status_cb):
            return status_cb
    return None


def resolve_rlm_progress_cb(context: ToolContext) -> RlmProgressFn | None:
    exec_ctx = context.tool_execution
    if exec_ctx is not None and exec_ctx.rlm is not None:
        on_progress = exec_ctx.rlm.on_progress
        if callable(on_progress):
            return on_progress
    return None
