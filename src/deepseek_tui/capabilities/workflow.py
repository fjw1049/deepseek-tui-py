"""Workflow capability prompt contributions."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from deepseek_tui.engine.events import StatusEvent, WorkflowProgressEvent
from deepseek_tui.host.prompts import (
    FunctionPromptContributor,
    PromptContributor,
    PromptContributorContext,
)
from deepseek_tui.host.tool_execution import (
    WorkflowToolExecution,
    clear_tool_execution_if_empty,
    ensure_tool_execution,
    resolve_workflow_cancel_event,
    resolve_workflow_emit,
    resolve_workflow_status_cb,
    resolve_workflow_tool_call_id,
)
from deepseek_tui.tools.context import ToolContext

logger = logging.getLogger(__name__)


def workflow_prompt_contributors() -> list[PromptContributor]:
    return [
        FunctionPromptContributor(
            "workflow-guidelines",
            700,
            _workflow_guidelines,
        )
    ]


def _workflow_guidelines(ctx: PromptContributorContext) -> str | None:
    if not ctx.workflow_guidelines:
        return None
    from deepseek_tui.workflow.prompts import workflow_guidelines_snippet

    return workflow_guidelines_snippet() or None


def workflow_mode_hint(mode: str) -> str:
    if mode != "workflow":
        return ""
    return (
        "\n\n[Turn hint] Use the workflow tool to decompose "
        "the user's request into a phased workflow spec."
    )


@contextmanager
def workflow_tool_bindings(
    context: ToolContext,
    *,
    cancel_event: object,
    tool_call_id: str,
    emit: Callable[[object], bool],
) -> Iterator[None]:
    def _workflow_emit(ev: WorkflowProgressEvent) -> None:
        if not emit(ev):
            if getattr(ev, "completed", False):
                logger.warning("workflow_completed_event_dropped queue_full")

    def _workflow_status(message: str) -> None:
        emit(StatusEvent(message))

    exec_ctx = ensure_tool_execution(context)
    prior_workflow = exec_ctx.workflow
    exec_ctx.workflow = WorkflowToolExecution(
        cancel_event=cancel_event,
        tool_call_id=tool_call_id,
        emit_progress=_workflow_emit,
        emit_status=_workflow_status,
    )
    try:
        yield
    finally:
        exec_ctx.workflow = prior_workflow
        clear_tool_execution_if_empty(context)


def resolve_workflow_spec(input_data: dict[str, Any]) -> Any:
    from deepseek_tui.workflow.validate import (
        WorkflowValidationError,
        parse_workflow_spec,
    )

    script = input_data.get("script")
    raw_spec = input_data.get("spec")
    if script is not None and not isinstance(script, str):
        raise WorkflowValidationError("script must be a string")
    if raw_spec is None and script is None:
        raise WorkflowValidationError("workflow requires spec or script+spec")
    if script:
        from deepseek_tui.workflow.adapters.pi_js import (
            PiJsParseError,
            parse_workflow_script,
        )

        try:
            meta, _body = parse_workflow_script(script)
        except PiJsParseError as exc:
            raise WorkflowValidationError(str(exc)) from exc
        if raw_spec is None:
            raise WorkflowValidationError(
                "script-only input is not supported; provide spec.phases (IR)"
            )
        if not isinstance(raw_spec, dict):
            raise WorkflowValidationError("spec must be an object when using script")
        merged = dict(raw_spec)
        merged["meta"] = {**(merged.get("meta") or {}), **meta}
        return parse_workflow_spec(merged)
    return parse_workflow_spec({"spec": raw_spec} if isinstance(raw_spec, dict) else raw_spec)


async def execute_workflow_tool(
    input_data: dict[str, Any],
    context: ToolContext,
) -> Any:
    from deepseek_tui.tools.base import ToolError, ToolResult
    from deepseek_tui.workflow.agent_runner import DeepSeekAgentRunner
    from deepseek_tui.workflow.models import (
        WorkflowAbortedError,
        WorkflowFailedError,
        WorkflowSnapshot,
    )
    from deepseek_tui.workflow.runtime import render_workflow_text, run_workflow
    from deepseek_tui.workflow.serialize import snapshot_to_dict
    from deepseek_tui.workflow.validate import WorkflowValidationError

    try:
        spec = resolve_workflow_spec(input_data)
    except WorkflowValidationError as exc:
        raise ToolError(f"workflow: invalid spec: {exc}") from exc

    manager = context.subagent_manager
    if manager is None:
        raise ToolError("workflow: SubAgentManager is not attached")
    loop_runtime = manager.loop_runtime
    if loop_runtime is None:
        raise ToolError("workflow: sub-agent loop runtime is not configured")

    cancel_event = resolve_workflow_cancel_event(context)
    tool_call_id = resolve_workflow_tool_call_id(context)
    emit = resolve_workflow_emit(context)
    spawned_ids: list[str] = []
    runner = DeepSeekAgentRunner(
        manager,
        loop_runtime,
        parent_depth=loop_runtime.spawn_depth,
        register_spawned=lambda aid: spawned_ids.append(aid),
    )
    last_snapshot = WorkflowSnapshot(
        name=spec.meta.name,
        description=spec.meta.description,
    )

    def emit_progress(
        snapshot: WorkflowSnapshot,
        *,
        completed: bool = False,
        status: str = "running",
    ) -> None:
        if not callable(emit):
            return
        emit(
            WorkflowProgressEvent(
                tool_call_id=tool_call_id,
                thread_id=None,
                workflow_name=spec.meta.name,
                snapshot=snapshot,
                completed=completed,
                status=status,
            )
        )

    def on_log(msg: str) -> None:
        emit_progress(
            WorkflowSnapshot(
                name=spec.meta.name,
                description=spec.meta.description,
                logs=[msg],
            )
        )

    def on_progress(snapshot: WorkflowSnapshot) -> None:
        nonlocal last_snapshot
        last_snapshot = snapshot
        emit_progress(snapshot)
        status_cb = resolve_workflow_status_cb(context)
        if status_cb is not None:
            status_cb(render_workflow_text(snapshot, completed=False))

    async def _run() -> ToolResult:
        try:
            result = await run_workflow(
                spec,
                runner=runner,
                cancel_event=cancel_event,
                manager=manager,
                on_log=on_log,
                on_progress=on_progress,
            )
        except WorkflowAbortedError:
            emit_progress(last_snapshot, completed=True, status="cancelled")
            return ToolResult(
                success=False,
                content="Workflow cancelled",
                metadata={
                    "workflow": {
                        "cancelled": True,
                        "snapshot": snapshot_to_dict(last_snapshot),
                    }
                },
            )
        except WorkflowFailedError as exc:
            emit_progress(last_snapshot, completed=True, status="failed")
            return ToolResult(
                success=False,
                content=f"Workflow failed: {exc}",
                metadata={
                    "workflow": {
                        "failed": True,
                        "snapshot": snapshot_to_dict(last_snapshot),
                    }
                },
            )
        except asyncio.CancelledError:
            emit_progress(last_snapshot, completed=True, status="cancelled")
            raise
        except Exception:
            emit_progress(last_snapshot, completed=True, status="failed")
            raise

        text = render_workflow_text(result.snapshot, completed=True)
        if result.result is not None:
            if isinstance(result.result, str):
                body = result.result
            else:
                body = json.dumps(result.result, indent=2, default=str)
            text = f"{text}\n\nResult:\n{body}"

        emit_progress(result.snapshot, completed=True, status="completed")

        errors_list = [{"step_id": e.step_id, "error": e.error} for e in result.errors]
        return ToolResult(
            success=True,
            content=text,
            metadata={
                "workflow": {
                    "name": spec.meta.name,
                    "snapshot": snapshot_to_dict(result.snapshot),
                    "result": result.result,
                    "logs": result.logs,
                    "duration_ms": result.duration_ms,
                    **({"errors": errors_list} if errors_list else {}),
                }
            },
        )

    timeout = spec.policy.wall_clock_seconds
    if timeout > 0:
        task = asyncio.create_task(_run())
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            cancel_event.set()
            for agent_id in list(spawned_ids):
                try:
                    await manager.cancel(agent_id)
                except KeyError:
                    pass
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError, Exception):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            emit_progress(last_snapshot, completed=True, status="timed_out")
            return ToolResult(
                success=False,
                content=f"Workflow timed out after {timeout}s",
                metadata={
                    "workflow": {
                        "timed_out": True,
                        "snapshot": snapshot_to_dict(last_snapshot),
                    }
                },
            )
    return await _run()
