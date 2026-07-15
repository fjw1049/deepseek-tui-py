"""``workflow`` tool — execute Workflow IR via in-process sub-agents."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.workflow.catalog import (
    WorkflowCatalogError,
    list_workflows,
    resolve_workflow,
)
from deepseek_tui.workflow.detach import encode_detach_prompt
from deepseek_tui.workflow.models import WorkflowSnapshot
from deepseek_tui.workflow.models import WorkflowAbortedError, WorkflowFailedError
from deepseek_tui.workflow.runtime import (
    DeepSeekAgentRunner,
    render_workflow_text,
    run_workflow,
)
from deepseek_tui.workflow.models import snapshot_to_dict
from deepseek_tui.workflow.models import WorkflowValidationError, parse_workflow_spec
from deepseek_tui.workflow.store import (
    WorkflowRunRecord,
    WorkflowRunStoreError,
    create_run,
    list_runs,
    load_run,
    safe_checkpoint_run,
    save_run,
)
from deepseek_tui.workflow.worktree import (
    WorkflowWorktreeError,
    ensure_run_worktree,
)


def _optional_bool(data: dict[str, Any], key: str) -> bool | None:
    raw = data.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    raise WorkflowValidationError(f"{key} must be a boolean")


def _worktree_meta(record: WorkflowRunRecord) -> dict[str, str]:
    out: dict[str, str] = {}
    if record.worktree_path:
        out["worktree_path"] = record.worktree_path
    if record.worktree_branch:
        out["worktree_branch"] = record.worktree_branch
    return out


def _prepare_worktree(
    run_record: WorkflowRunRecord,
    *,
    spec: Any,
    cwd: Path,
) -> Path | None:
    """Ensure worktree when policy requests it; return agent workspace override."""
    wants = spec.policy.worktree == "on" or bool(run_record.worktree_path)
    if not wants:
        return None
    try:
        info = ensure_run_worktree(
            run_record.run_id,
            workspace=cwd,
            existing_path=run_record.worktree_path,
            existing_branch=run_record.worktree_branch,
        )
    except WorkflowWorktreeError as exc:
        raise ToolError(f"workflow: {exc}") from exc
    run_record.worktree_path = str(info.path)
    run_record.worktree_branch = info.branch
    save_run(run_record, workspace=cwd)
    return info.path


class WorkflowTool(ToolSpec):
    """Run a structured multi-agent workflow in one tool call."""

    def name(self) -> str:
        return "workflow"

    def description(self) -> str:
        return (
            "Execute a structured multi-agent workflow. Prefer a named workflow "
            "with `name` + `task` when one fits (bundled: `repo_review`, "
            "`diff_review`, `spec_check`). Discovery roots (higher wins): "
            "`<cwd>/workflows/`, `<cwd>/.deepseek/workflows/`, "
            "`~/.deepseek/workflows/`, then built-in presets. Pass `spec` for "
            "ad-hoc IR. Resume an interrupted run with `run_id` alone. "
            "Do not combine `run_id` with `name`/`spec`. Call `workflow_list` "
            "to enumerate available workflows and recent runs.\n\n"
            "IR step types: `agent`, `fanout` (`items` or `items_from`), "
            "`pipeline`, `loop` (`max_rounds` + optional `until`), "
            "`synthesis`. Templates: `{{task}}`, `{{item}}`, `{{round}}`, "
            "`{{outputs.<id>}}`.\n\n"
            "Optional: `policy.worktree: \"on\"` isolates edits in a git "
            "worktree; `detach: true` enqueues via TaskManager and returns "
            "`run_id` + `task_id` immediately.\n\n"
            "Runs are checkpointed under `.deepseek/workflow-runs/<run_id>/`."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Named workflow id (e.g. repo_review). Mutually "
                        "exclusive with spec/run_id. Pair with task."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "Runtime task text injected as {{task}} in prompts. "
                        "Required when using name; optional with spec."
                    ),
                },
                "run_id": {
                    "type": "string",
                    "description": (
                        "Resume a previously interrupted/failed workflow run "
                        "from `.deepseek/workflow-runs/`. Mutually exclusive "
                        "with name/spec."
                    ),
                },
                "spec": {
                    "type": "object",
                    "description": (
                        "Workflow IR v1. Mutually exclusive with name/run_id."
                    ),
                },
                "script": {
                    "type": "string",
                    "description": (
                        "Optional Pi-style JS meta export; must pair with spec."
                    ),
                },
                "detach": {
                    "type": "boolean",
                    "description": (
                        "If true, create/checkpoint the run and enqueue a "
                        "TaskManager job that drives it to completion; return "
                        "run_id + task_id immediately without waiting."
                    ),
                },
            },
            "anyOf": [
                {"required": ["name", "task"]},
                {"required": ["spec"]},
                {"required": ["script", "spec"]},
                {"required": ["run_id"]},
            ],
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    def _resolve_spec(
        self, input_data: dict[str, Any], *, cwd: Path | None = None
    ) -> Any:
        run_id = input_data.get("run_id")
        name = input_data.get("name")
        script = input_data.get("script")
        raw_spec = input_data.get("spec")

        if run_id is not None and not isinstance(run_id, str):
            raise WorkflowValidationError("run_id must be a string")
        if name is not None and not isinstance(name, str):
            raise WorkflowValidationError("name must be a string")
        if script is not None and not isinstance(script, str):
            raise WorkflowValidationError("script must be a string")

        if run_id and (name or raw_spec is not None or script):
            raise WorkflowValidationError(
                "run_id is mutually exclusive with name/spec/script"
            )
        if name and raw_spec is not None:
            raise WorkflowValidationError(
                "name and spec are mutually exclusive; pass one"
            )
        if name and script:
            raise WorkflowValidationError(
                "name and script are mutually exclusive; pass one"
            )

        if run_id:
            # Spec loaded from the run record in execute().
            return None

        if name:
            name = name.strip()
            if not name:
                raise WorkflowValidationError("name must be a non-empty string")
            task = input_data.get("task")
            if not isinstance(task, str) or not task.strip():
                raise WorkflowValidationError(
                    "task is required when using a named workflow"
                )
            try:
                return resolve_workflow(name, cwd=cwd)
            except WorkflowCatalogError as exc:
                raise WorkflowValidationError(str(exc)) from exc

        if raw_spec is None and script is None:
            raise WorkflowValidationError(
                "workflow requires name+task, spec, script+spec, or run_id"
            )
        if script:
            from deepseek_tui.workflow.adapters import (
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
        return parse_workflow_spec(
            {"spec": raw_spec} if isinstance(raw_spec, dict) else raw_spec
        )

    async def _enqueue_detach(
        self,
        *,
        run_record: WorkflowRunRecord,
        context: ToolContext,
        cwd: Path,
        spec: Any,
    ) -> ToolResult:
        task_manager = context.task_manager
        if task_manager is None:
            raise ToolError(
                "workflow: detach requires TaskManager (features.tasks=True)"
            )
        from deepseek_tui.tools.task.models import NewTaskRequest

        _prepare_worktree(run_record, spec=spec, cwd=cwd)
        prompt = encode_detach_prompt(run_id=run_record.run_id, workspace=cwd)
        task = await task_manager.add_task(
            NewTaskRequest(
                prompt=prompt,
                workspace=str(cwd),
                auto_approve=True,
                thread_id=(
                    context.metadata.get("runtime_thread_id")
                    if isinstance(context.metadata.get("runtime_thread_id"), str)
                    else None
                ),
            )
        )
        run_record.task_id = task.id
        run_record.status = "running"
        save_run(run_record, workspace=cwd)

        wt = _worktree_meta(run_record)
        lines = [
            f"Workflow detached: run_id={run_record.run_id}",
            f"task_id={task.id}",
            "Progress continues in the TASKS panel; cancel with task_cancel.",
        ]
        if wt.get("worktree_path"):
            lines.append(f"worktree_path={wt['worktree_path']}")
            lines.append(f"worktree_branch={wt.get('worktree_branch', '')}")
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "workflow": {
                    "detached": True,
                    "run_id": run_record.run_id,
                    "task_id": task.id,
                    "name": spec.meta.name,
                    **wt,
                }
            },
        )

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        cwd = context.working_directory
        run_id_raw = input_data.get("run_id")
        resume_record: WorkflowRunRecord | None = None
        skip_step_ids: set[str] | None = None
        initial_outputs = None

        try:
            detach = _optional_bool(input_data, "detach") or False
            if isinstance(run_id_raw, str) and run_id_raw.strip():
                try:
                    resume_record = load_run(run_id_raw.strip(), workspace=cwd)
                except WorkflowRunStoreError as exc:
                    raise WorkflowValidationError(str(exc)) from exc
                if resume_record.status == "completed":
                    raise WorkflowValidationError(
                        f"run {resume_record.run_id} already completed"
                    )
                spec = resume_record.parsed_spec()
                runtime_task = resume_record.task
                skip_step_ids = set(resume_record.completed_step_ids)
                initial_outputs = resume_record.restored_outputs()
            else:
                spec = self._resolve_spec(input_data, cwd=cwd)
                runtime_task = input_data.get("task")
                if runtime_task is not None and not isinstance(runtime_task, str):
                    raise WorkflowValidationError("task must be a string")
                runtime_task = (runtime_task or "").strip()
        except WorkflowValidationError as exc:
            raise ToolError(f"workflow: invalid spec: {exc}") from exc

        if spec is None:
            raise ToolError("workflow: failed to resolve spec")

        run_record = resume_record or create_run(
            spec, task=runtime_task, workspace=cwd
        )
        if resume_record is not None:
            run_record.status = "running"
            run_record.error = None
            save_run(run_record, workspace=cwd)

        if detach:
            return await self._enqueue_detach(
                run_record=run_record,
                context=context,
                cwd=cwd,
                spec=spec,
            )

        agent_workspace = _prepare_worktree(run_record, spec=spec, cwd=cwd)

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
            workspace=agent_workspace,
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
                    run_id=run_record.run_id,
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
            # Structured WorkflowProgressEvent only — do not also emit StatusEvent
            # text (that becomes duplicate system pills in workbench).
            emit_progress(snapshot)

        def on_checkpoint(ctx_obj: Any, snap: WorkflowSnapshot, logs: list[str]) -> None:
            nonlocal last_snapshot
            last_snapshot = snap
            safe_checkpoint_run(
                run_record,
                completed_step_ids=list(ctx_obj.completed_step_ids),
                outputs=dict(ctx_obj.outputs),
                snapshot=snap,
                logs=logs,
                status="running",
                workspace=cwd,
            )

        def _result_meta(extra: dict[str, Any]) -> dict[str, Any]:
            return {
                "workflow": {
                    **extra,
                    **_worktree_meta(run_record),
                }
            }

        async def _run() -> ToolResult:
            try:
                result = await run_workflow(
                    spec,
                    runner=runner,
                    cancel_event=cancel_event,
                    manager=manager,
                    on_log=on_log,
                    on_progress=on_progress,
                    on_checkpoint=on_checkpoint,
                    task=runtime_task,
                    initial_outputs=initial_outputs,
                    skip_step_ids=skip_step_ids,
                )
            except WorkflowAbortedError:
                safe_checkpoint_run(
                    run_record,
                    completed_step_ids=list(run_record.completed_step_ids),
                    outputs=run_record.restored_outputs(),
                    snapshot=last_snapshot,
                    logs=list(run_record.logs),
                    status="cancelled",
                    error="cancelled",
                    workspace=cwd,
                )
                emit_progress(last_snapshot, completed=True, status="cancelled")
                return ToolResult(
                    success=False,
                    content=(
                        f"Workflow cancelled (run_id={run_record.run_id}). "
                        "Resume with workflow({run_id: ...})."
                    ),
                    metadata=_result_meta(
                        {
                            "cancelled": True,
                            "run_id": run_record.run_id,
                            "snapshot": snapshot_to_dict(last_snapshot),
                        }
                    ),
                )
            except WorkflowFailedError as exc:
                safe_checkpoint_run(
                    run_record,
                    completed_step_ids=list(run_record.completed_step_ids),
                    outputs=run_record.restored_outputs(),
                    snapshot=last_snapshot,
                    logs=list(run_record.logs),
                    status="failed",
                    error=str(exc),
                    workspace=cwd,
                )
                emit_progress(last_snapshot, completed=True, status="failed")
                return ToolResult(
                    success=False,
                    content=(
                        f"Workflow failed: {exc} (run_id={run_record.run_id}). "
                        "Resume with workflow({run_id: ...})."
                    ),
                    metadata=_result_meta(
                        {
                            "failed": True,
                            "run_id": run_record.run_id,
                            "snapshot": snapshot_to_dict(last_snapshot),
                        }
                    ),
                )
            except asyncio.CancelledError:
                safe_checkpoint_run(
                    run_record,
                    completed_step_ids=list(run_record.completed_step_ids),
                    outputs=run_record.restored_outputs(),
                    snapshot=last_snapshot,
                    logs=list(run_record.logs),
                    status="interrupted",
                    error="interrupted",
                    workspace=cwd,
                )
                emit_progress(last_snapshot, completed=True, status="cancelled")
                raise
            except Exception as exc:
                safe_checkpoint_run(
                    run_record,
                    completed_step_ids=list(run_record.completed_step_ids),
                    outputs=run_record.restored_outputs(),
                    snapshot=last_snapshot,
                    logs=list(run_record.logs),
                    status="interrupted",
                    error=str(exc),
                    workspace=cwd,
                )
                emit_progress(last_snapshot, completed=True, status="failed")
                raise

            safe_checkpoint_run(
                run_record,
                completed_step_ids=list(run_record.completed_step_ids),
                outputs=run_record.restored_outputs(),
                snapshot=result.snapshot,
                logs=list(result.logs),
                status="completed",
                result=result.result,
                workspace=cwd,
            )

            text = render_workflow_text(result.snapshot, completed=True)
            if result.result is not None:
                if isinstance(result.result, str):
                    body = result.result
                else:
                    body = json.dumps(result.result, indent=2, default=str)
                text = f"{text}\n\nResult:\n{body}"
            text = f"{text}\n\nrun_id: {run_record.run_id}"
            wt = _worktree_meta(run_record)
            if wt.get("worktree_path"):
                text = (
                    f"{text}\nworktree_path: {wt['worktree_path']}\n"
                    f"worktree_branch: {wt.get('worktree_branch', '')}"
                )

            emit_progress(result.snapshot, completed=True, status="completed")

            errors_list = [
                {"step_id": e.step_id, "error": e.error}
                for e in result.errors
            ]
            return ToolResult(
                success=True,
                content=text,
                metadata=_result_meta(
                    {
                        "name": spec.meta.name,
                        "run_id": run_record.run_id,
                        "snapshot": snapshot_to_dict(result.snapshot),
                        "result": result.result,
                        "logs": result.logs,
                        "duration_ms": result.duration_ms,
                        **({"errors": errors_list} if errors_list else {}),
                    }
                ),
            )

        timeout = spec.policy.wall_clock_seconds
        if timeout > 0:
            timeout_task = asyncio.create_task(_run())
            try:
                return await asyncio.wait_for(
                    asyncio.shield(timeout_task), timeout=timeout
                )
            except TimeoutError:
                cancel_event.set()
                for agent_id in list(spawned_ids):
                    try:
                        await manager.cancel(agent_id)
                    except KeyError:
                        pass
                grace_result: ToolResult | None = None
                try:
                    grace_result = await asyncio.wait_for(timeout_task, timeout=5.0)
                except (TimeoutError, asyncio.CancelledError, Exception):
                    timeout_task.cancel()
                    try:
                        await timeout_task
                    except (asyncio.CancelledError, Exception):
                        pass
                # Prefer orderly shutdown result, but always mark the run timed_out
                # (cancel_event makes the inner path look like "cancelled").
                safe_checkpoint_run(
                    run_record,
                    completed_step_ids=list(run_record.completed_step_ids),
                    outputs=run_record.restored_outputs(),
                    snapshot=last_snapshot,
                    logs=list(run_record.logs),
                    status="timed_out",
                    error="timed_out",
                    workspace=cwd,
                )
                emit_progress(last_snapshot, completed=True, status="timed_out")
                timed_out_content = (
                    f"Workflow timed out after {timeout}s "
                    f"(run_id={run_record.run_id}). "
                    "Resume with workflow({run_id: ...})."
                )
                if grace_result is not None and grace_result.success:
                    return grace_result
                meta = _result_meta(
                    {
                        "timed_out": True,
                        "run_id": run_record.run_id,
                        "snapshot": snapshot_to_dict(last_snapshot),
                    }
                )
                if grace_result is not None and isinstance(grace_result.metadata, dict):
                    # Keep any richer metadata from the cancelled path, override flags.
                    merged = dict(grace_result.metadata)
                    wf = dict(merged.get("workflow") or {})
                    wf.update(meta["workflow"])
                    merged["workflow"] = wf
                    meta = merged
                return ToolResult(
                    success=False,
                    content=timed_out_content,
                    metadata=meta,
                )
        return await _run()


class WorkflowListTool(ToolSpec):
    """List available named workflows and recent workflow runs."""

    def name(self) -> str:
        return "workflow_list"

    def description(self) -> str:
        return (
            "List available named workflows (bundled presets, project, and user "
            "scopes) plus recent workflow runs. Use this to discover a workflow "
            "name before calling `workflow` with `name`, or to find a `run_id` "
            "to resume. Read-only."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "runs_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Max recent runs to return (default 20).",
                }
            },
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.AUTO

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        cwd = context.working_directory
        runs_limit_val = input_data.get("runs_limit")
        runs_limit = (
            int(runs_limit_val) if isinstance(runs_limit_val, int) else 20
        )

        workflows = [
            {"name": w.name, "description": w.description, "source": w.source}
            for w in list_workflows(cwd=cwd)
        ]

        runs: list[dict[str, Any]] = []
        for record in list_runs(workspace=cwd, limit=runs_limit):
            runs.append(
                {
                    "run_id": record.run_id,
                    "status": record.status,
                    "task": record.task,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "completed_steps": len(record.completed_step_ids),
                }
            )

        content = f"{len(workflows)} workflow(s), {len(runs)} run(s)"
        if workflows:
            content += "; workflows: " + ", ".join(w["name"] for w in workflows)
        return ToolResult(
            success=True,
            content=content,
            metadata={"workflows": workflows, "runs": runs},
        )
