"""``workflow`` tool — execute Workflow IR via in-process sub-agents."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.workflow.agent_runner import DeepSeekAgentRunner
from deepseek_tui.workflow.models import WorkflowSnapshot
from deepseek_tui.workflow.models import WorkflowAbortedError, WorkflowFailedError
from deepseek_tui.workflow.runtime import (
    render_workflow_text,
    run_workflow,
)
from deepseek_tui.workflow.serialize import snapshot_to_dict
from deepseek_tui.workflow.validate import WorkflowValidationError, parse_workflow_spec


class WorkflowTool(ToolSpec):
    """Run a structured multi-agent workflow in one tool call."""

    def name(self) -> str:
        return "workflow"

    def description(self) -> str:
        return (
            "Execute a structured multi-agent workflow from a JSON Workflow IR "
            "(`spec` object). If the user explicitly asks to use workflow, or "
            "wants orchestrated fan-out/fan-in, phased review, or parallel "
            "exploration, call this tool instead of manually coordinating "
            "`agent_spawn` / `agent_wait`. Do not use it for a single simple "
            "task.\n\n"
            "Pass a complete `spec` with `meta`, `policy`, and `phases` (each "
            "phase has `steps`). Step types: `agent` (one spawn), `fanout` "
            "(parallel per item), `pipeline` (per-item stages), `synthesis` "
            "(merge prior outputs via `{{outputs.<step_id>}}` templates).\n\n"
            "Each `agent` step needs `label` + `prompt`. Each `fanout` step "
            "needs `items` and an `agent` object containing `label_template` "
            "and `prompt_template`, for example: `{type:'fanout', items:[...], "
            "agent:{label_template:'inspect {{item}}', prompt_template:'...'}}`. "
            "Use `fanout` for parallel items — do not spawn many separate "
            "agents manually. Include a `synthesis` step when merging branches. "
            "Sub-agents do not inherit implicit repo context; put paths and "
            "tasks in prompts. Failed steps may be omitted — synthesis must "
            "handle missing outputs.\n\n"
            "Prefer `spec` (Workflow IR JSON). Optional `script` (Pi JS with "
            "`export const meta`) requires `spec.phases` — script bodies are not "
            "executed in Python."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "description": (
                        "Workflow IR v1: version, meta {name, description}, "
                        "policy, phases[].steps[]"
                    ),
                },
                "script": {
                    "type": "string",
                    "description": (
                        "Optional Pi-style JS workflow script with "
                        "`export const meta = { name, description }`. "
                        "Must be paired with `spec.phases` (meta from script "
                        "overrides spec.meta when both are present)."
                    ),
                },
            },
            "anyOf": [{"required": ["spec"]}, {"required": ["script", "spec"]}],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    def _resolve_spec(self, input_data: dict[str, Any]) -> Any:
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

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            spec = self._resolve_spec(input_data)
        except WorkflowValidationError as exc:
            raise ToolError(f"workflow: invalid spec: {exc}") from exc

        manager = context.subagent_manager
        if manager is None:
            raise ToolError("workflow: SubAgentManager is not attached")
        loop_runtime = manager.loop_runtime
        if loop_runtime is None:
            raise ToolError("workflow: sub-agent loop runtime is not configured")

        cancel_event = context.metadata.get("engine_cancel_event")
        if not isinstance(cancel_event, asyncio.Event):
            cancel_event = asyncio.Event()

        tool_call_id = context.metadata.get("workflow_tool_call_id")
        if not isinstance(tool_call_id, str):
            tool_call_id = ""

        emit = context.metadata.get("workflow_emit")
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
            from deepseek_tui.engine.events import WorkflowProgressEvent

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
            status_cb = context.metadata.get("workflow_status_cb")
            if callable(status_cb):
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

            errors_list = [
                {"step_id": e.step_id, "error": e.error}
                for e in result.errors
            ]
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
