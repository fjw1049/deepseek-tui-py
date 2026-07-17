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
    acquire_run_lease,
    clear_stop_intent,
    create_run,
    has_stop_intent,
    heartbeat_run_lease,
    is_run_actively_running,
    list_runs,
    load_run,
    release_run_lease,
    safe_checkpoint_run,
    save_run,
    write_stop_intent,
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


async def _prepare_worktree(
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
        # ``ensure_run_worktree`` shells out to git synchronously (up to ~120s);
        # push it off the event loop so a slow worktree add doesn't stall every
        # other concurrent agent/task in this process.
        info = await asyncio.to_thread(
            ensure_run_worktree,
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
            "Execute a structured multi-agent workflow (DAG ready-set scheduler). "
            "Prefer a named workflow with `name` + `task` when one fits (bundled: "
            "`repo_review`, `diff_review`, `spec_check`, `adaptive`). Discovery "
            "roots (higher wins): `<cwd>/workflows/`, `<cwd>/.deepseek/workflows/`, "
            "`~/.deepseek/workflows/`, then built-in presets. Pass `spec` for "
            "ad-hoc IR (v1 phases or v2 graph). Pass `mode: \"dynamic\"` for the "
            "builtin adaptive dynamic-controller root. Resume an interrupted run "
            "with `run_id` alone. Do not combine `run_id` with `name`/`spec`. "
            "Call `workflow_list` to enumerate available workflows and recent runs.\n\n"
            "IR step types: `agent`, `fanout` (`items` or `items_from`), "
            "`pipeline`, `loop` (`max_rounds` + optional `until`), `reduce`, "
            "`synthesis`, `dag`, `dynamic`, `support`. Templates: `{{task}}`, "
            "`{{item}}`, `{{round}}`, `{{outputs.<id>}}`.\n\n"
            "Optional: `policy.worktree: \"on\"` isolates edits in a git "
            "worktree; `detach: true` enqueues via TaskManager and returns "
            "`run_id` + `task_id` immediately.\n\n"
            "Runs are checkpointed under `.deepseek/workflow-runs/<run_id>/` "
            "after every completed step (and every finished fanout/pipeline "
            "item), including runtime graph mutations from `dynamic` nodes."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Named workflow id (e.g. repo_review, adaptive). Mutually "
                        "exclusive with spec/run_id/mode. Pair with task."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "Runtime task text injected as {{task}} in prompts. "
                        "Required when using name or mode=dynamic; optional with spec."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["dynamic"],
                    "description": (
                        "Sugar for the builtin adaptive dynamic workflow "
                        "(single dynamic root). Pair with task. Mutually exclusive "
                        "with name/spec/run_id."
                    ),
                },
                "run_id": {
                    "type": "string",
                    "description": (
                        "Resume a previously interrupted/failed workflow run "
                        "from `.deepseek/workflow-runs/`. Mutually exclusive "
                        "with name/spec/mode."
                    ),
                },
                "spec": {
                    "type": "object",
                    "description": (
                        "Workflow IR v1 (phases) or v2 (graph). Mutually exclusive "
                        "with name/run_id/mode."
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
                {"required": ["mode", "task"]},
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
        mode = input_data.get("mode")

        if run_id is not None and not isinstance(run_id, str):
            raise WorkflowValidationError("run_id must be a string")
        if name is not None and not isinstance(name, str):
            raise WorkflowValidationError("name must be a string")
        if script is not None and not isinstance(script, str):
            raise WorkflowValidationError("script must be a string")
        if mode is not None and mode != "dynamic":
            raise WorkflowValidationError('mode must be "dynamic" when set')

        if run_id and (name or raw_spec is not None or script or mode):
            raise WorkflowValidationError(
                "run_id is mutually exclusive with name/spec/script/mode"
            )
        if name and raw_spec is not None:
            raise WorkflowValidationError(
                "name and spec are mutually exclusive; pass one"
            )
        if name and script:
            raise WorkflowValidationError(
                "name and script are mutually exclusive; pass one"
            )
        if mode and (name or raw_spec is not None or script):
            raise WorkflowValidationError(
                "mode is mutually exclusive with name/spec/script"
            )

        if run_id:
            # Spec loaded from the run record in execute().
            return None

        if mode == "dynamic":
            task = input_data.get("task")
            if not isinstance(task, str) or not task.strip():
                raise WorkflowValidationError(
                    "task is required when using mode=dynamic"
                )
            from deepseek_tui.workflow.models import adaptive_workflow_spec

            return parse_workflow_spec(
                adaptive_workflow_spec(task_description=task.strip())
            )

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
                "workflow requires name+task, mode+task, spec, script+spec, or run_id"
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

        await _prepare_worktree(run_record, spec=spec, cwd=cwd)
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
        initial_graph = None

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
                if is_run_actively_running(resume_record, workspace=cwd):
                    raise WorkflowValidationError(
                        f"run {resume_record.run_id} appears to still be running "
                        "(active lease or recent checkpoint); wait for it to finish or "
                        "cancel it before resuming"
                    )
                # Deliberate resume of a non-live run: drop any leftover stop
                # intent so the driver can continue. A live run that still has
                # stop-intent is honored below after lease acquire.
                if resume_record.status != "running":
                    clear_stop_intent(resume_record.run_id, workspace=cwd)
                spec = resume_record.parsed_spec()
                runtime_task = resume_record.task
                skip_step_ids = set(resume_record.completed_step_ids)
                initial_outputs = resume_record.restored_outputs()
                # Attach resume bags for scheduler (dynamic mutations / skips).
                setattr(spec, "_resume_ctx", resume_record.resume_ctx_bag())
                if isinstance(resume_record.runtime_graph, dict):
                    from deepseek_tui.workflow.dag import CompiledGraph

                    initial_graph = CompiledGraph.from_dict(resume_record.runtime_graph)
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

        try:
            lease_token = acquire_run_lease(run_record.run_id, workspace=cwd)
        except WorkflowRunStoreError as exc:
            raise ToolError(f"workflow: {exc}") from exc

        # Crash mid-cancel left stop-intent while status stayed "running".
        # Honor it immediately so we don't continue work after a stop request.
        if has_stop_intent(run_record.run_id, workspace=cwd):
            safe_checkpoint_run(
                run_record,
                completed_step_ids=list(run_record.completed_step_ids),
                outputs=run_record.restored_outputs(),
                snapshot=WorkflowSnapshot(
                    name=spec.meta.name,
                    description=spec.meta.description,
                ),
                logs=list(run_record.logs),
                status="cancelled",
                error="cancelled",
                workspace=cwd,
            )
            clear_stop_intent(run_record.run_id, workspace=cwd)
            release_run_lease(run_record.run_id, lease_token, workspace=cwd)
            return ToolResult(
                success=False,
                content=(
                    f"Workflow cancelled via durable stop-intent "
                    f"(run_id={run_record.run_id}). "
                    "Resume with workflow({run_id: ...}) to continue."
                ),
                metadata={
                    "workflow": {
                        "cancelled": True,
                        "run_id": run_record.run_id,
                        "stop_intent": True,
                    }
                },
            )

        agent_workspace = await _prepare_worktree(run_record, spec=spec, cwd=cwd)

        manager = context.subagent_manager
        if manager is None:
            release_run_lease(run_record.run_id, lease_token, workspace=cwd)
            raise ToolError("workflow: SubAgentManager is not attached")
        loop_runtime = manager.loop_runtime
        if loop_runtime is None:
            release_run_lease(run_record.run_id, lease_token, workspace=cwd)
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

        def on_log(_msg: str) -> None:
            # Scheduler already appends onto the shared snapshot.logs list
            # before calling on_log. Re-emit that full snapshot — never a
            # sparse skeleton (which wiped nodes/agents in ProcessTray).
            # Skip pre-progress policy logs (empty last_snapshot).
            if not last_snapshot.agents and not last_snapshot.nodes:
                return
            emit_progress(last_snapshot)

        def on_progress(snapshot: WorkflowSnapshot) -> None:
            nonlocal last_snapshot
            last_snapshot = snapshot
            # Structured WorkflowProgressEvent only — do not also emit StatusEvent
            # text (that becomes duplicate system pills in workbench).
            emit_progress(snapshot)

        def on_checkpoint(ctx_obj: Any, snap: WorkflowSnapshot, logs: list[str]) -> None:
            nonlocal last_snapshot
            last_snapshot = snap
            heartbeat_run_lease(run_record.run_id, lease_token, workspace=cwd)
            safe_checkpoint_run(
                run_record,
                completed_step_ids=list(ctx_obj.completed_step_ids),
                outputs=dict(ctx_obj.outputs),
                snapshot=snap,
                logs=logs,
                status="running",
                workspace=cwd,
                runtime_graph=getattr(ctx_obj, "runtime_graph", None),
                dynamic_states=dict(getattr(ctx_obj, "dynamic_states", {}) or {}),
                budgets_used=dict(getattr(ctx_obj, "budgets_used", {}) or {}),
                generated_node_ids=list(
                    getattr(ctx_obj, "generated_node_ids", []) or []
                ),
                skipped_step_ids=list(getattr(ctx_obj, "skipped_step_ids", []) or []),
                failed_step_ids=list(getattr(ctx_obj, "failed_step_ids", []) or []),
                estimated_tokens_used=int(
                    getattr(ctx_obj, "estimated_tokens_used", 0) or 0
                ),
            )

        def _result_meta(extra: dict[str, Any]) -> dict[str, Any]:
            # Always attach spawned ids so the orchestrator can mark their
            # parent-completion handoff as already consumed (workflow result
            # already carries the synthesis). Otherwise a successful workflow
            # injects ``Resuming turn with N sub-agent completion(s)`` and
            # forces a second, layered final answer.
            return {
                "workflow": {
                    **extra,
                    **_worktree_meta(run_record),
                    "spawned_agent_ids": list(spawned_ids),
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
                    initial_graph=initial_graph,
                    cwd=cwd,
                    run_id=run_record.run_id,
                )
            except WorkflowAbortedError:
                write_stop_intent(run_record.run_id, workspace=cwd)
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
                clear_stop_intent(run_record.run_id, workspace=cwd)
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
                write_stop_intent(run_record.run_id, workspace=cwd)
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
            clear_stop_intent(run_record.run_id, workspace=cwd)

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
        try:
            if timeout > 0:
                timeout_task = asyncio.create_task(_run())
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(timeout_task), timeout=timeout
                    )
                except TimeoutError:
                    cancel_event.set()
                    write_stop_intent(run_record.run_id, workspace=cwd)
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
                    if grace_result is not None and grace_result.success:
                        # _run() already reached its own "completed" checkpoint
                        # (with the real result) inside the grace window — do not
                        # clobber it with a "timed_out" overwrite below, which
                        # would also wipe the persisted result (checkpoint_run's
                        # result defaults to None) and make a finished run look
                        # resumable/re-runnable.
                        return grace_result
                    # Cancelled but never reached its own terminal checkpoint —
                    # mark it timed_out so resume can pick up where it left off.
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
        finally:
            release_run_lease(run_record.run_id, lease_token, workspace=cwd)


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
