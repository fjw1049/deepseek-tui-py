"""Detached workflow execution via TaskManager (not a standalone supervise daemon)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from deepseek_tui.tools.task.models import (
    ExecutionTask,
    ExecutorFunc,
    TaskExecutionResult,
)

WORKFLOW_DETACH_MARKER = "[workflow-detach]"
_DETACH_RE = re.compile(
    r"^\[workflow-detach\]\s+run_id=(?P<run_id>\S+)\s+workspace=(?P<workspace>.+)\s*$"
)


def encode_detach_prompt(*, run_id: str, workspace: Path | str) -> str:
    """Build the durable-task prompt that workers recognize as a workflow resume job."""
    return (
        f"{WORKFLOW_DETACH_MARKER} run_id={run_id} "
        f"workspace={Path(workspace).resolve()}"
    )


def parse_detach_prompt(prompt: str) -> dict[str, str] | None:
    """Return ``{run_id, workspace}`` if *prompt* is a detach job, else None."""
    text = (prompt or "").strip()
    if not text.startswith(WORKFLOW_DETACH_MARKER):
        return None
    match = _DETACH_RE.match(text)
    if not match:
        return None
    return {
        "run_id": match.group("run_id").strip(),
        "workspace": match.group("workspace").strip(),
    }


def is_workflow_detach_prompt(prompt: str) -> bool:
    return parse_detach_prompt(prompt) is not None


def wrap_task_executor_for_workflow_detach(inner: ExecutorFunc) -> ExecutorFunc:
    """Run detach workflow jobs in-process; forward all other tasks to *inner*."""

    async def _wrapped(
        task: ExecutionTask, cancel: asyncio.Event
    ) -> TaskExecutionResult:
        if is_workflow_detach_prompt(task.prompt):
            return await execute_detached_workflow(task, cancel)
        return await inner(task, cancel)

    return _wrapped


async def execute_detached_workflow(
    task: ExecutionTask, cancel: asyncio.Event
) -> TaskExecutionResult:
    """Drive ``run_workflow`` for a checkpointed run until a terminal status."""
    parsed = parse_detach_prompt(task.prompt)
    if parsed is None:
        return TaskExecutionResult(
            summary="", error="invalid workflow-detach prompt"
        )

    from deepseek_tui.client.factory import build_llm_client
    from deepseek_tui.config.loader import ConfigLoader
    from deepseek_tui.tools.runtime import build_subagent_manager
    from deepseek_tui.tools.subagent import SubAgentRuntime
    from deepseek_tui.workflow.models import (
        WorkflowAbortedError,
        WorkflowFailedError,
        WorkflowSnapshot,
    )
    from deepseek_tui.workflow.runtime import DeepSeekAgentRunner, run_workflow
    from deepseek_tui.workflow.store import (
        WorkflowRunStoreError,
        acquire_run_lease,
        clear_stop_intent,
        has_stop_intent,
        heartbeat_run_lease,
        is_run_actively_running,
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

    project_cwd = Path(parsed["workspace"]).resolve()
    run_id = parsed["run_id"]
    try:
        record = load_run(run_id, workspace=project_cwd)
    except WorkflowRunStoreError as exc:
        return TaskExecutionResult(summary="", error=str(exc))

    if record.status == "completed":
        return TaskExecutionResult(
            summary=f"Workflow {record.run_id} already completed",
            detail=json.dumps({"run_id": record.run_id, "status": "completed"}),
        )

    # Durable stop left by a previous cancel/crash: finish as cancelled
    # instead of continuing work. Deliberate resume of a non-running run
    # clears stop-intent first (see branch below).
    if has_stop_intent(run_id, workspace=project_cwd) and record.status == "running":
        snap_meta = record.parsed_spec().meta
        safe_checkpoint_run(
            record,
            completed_step_ids=list(record.completed_step_ids),
            outputs=record.restored_outputs(),
            snapshot=WorkflowSnapshot(
                name=snap_meta.name,
                description=snap_meta.description,
            ),
            logs=list(record.logs),
            status="cancelled",
            error="cancelled",
            workspace=project_cwd,
        )
        clear_stop_intent(run_id, workspace=project_cwd)
        return TaskExecutionResult(
            summary=f"Workflow {record.run_id} cancelled",
            error="cancelled",
            detail=json.dumps(
                {
                    "run_id": record.run_id,
                    "status": "cancelled",
                    "stop_intent": True,
                }
            ),
        )

    if record.status != "running":
        clear_stop_intent(run_id, workspace=project_cwd)

    # If TaskManager already requested cancel before we started driving,
    # persist that intent before any agent work.
    if cancel.is_set():
        write_stop_intent(run_id, workspace=project_cwd)

    # Defense in depth: WorkflowTool.execute() already gates resume through
    # is_run_actively_running(), but that only covers the caller path that
    # created *this* task. If some other task_id is (or was, recently) driving
    # this same run_id — e.g. a stale detach task requeued by
    # TaskManager.resume_task() racing a still-live one — don't drive it too.
    # record.task_id is set to *this* task's id before it is ever queued (see
    # _enqueue_detach), so a mismatch here means a different task owns it.
    if (
        record.task_id is not None
        and record.task_id != task.id
        and is_run_actively_running(record, workspace=project_cwd)
    ):
        return TaskExecutionResult(
            summary="",
            error=(
                f"workflow run {record.run_id} is already being driven by "
                f"task {record.task_id}"
            ),
        )

    # Acquire the exclusive run lease so a concurrent caller (a sync
    # WorkflowTool resume, or a second requeued detach task) cannot
    # double-drive this run while we hold it. The sync path acquires the
    # same lease; detach previously skipped it, which left the
    # >ACTIVE_RUN_STALE_SECONDS window open to double-drive (two drivers
    # racing on run.json and duplicating agent spawns).
    try:
        lease_token = acquire_run_lease(run_id, workspace=project_cwd)
    except WorkflowRunStoreError as exc:
        return TaskExecutionResult(
            summary="",
            error=f"workflow run {run_id} already has a live driver: {exc}",
        )

    spec = record.parsed_spec()
    agent_cwd = project_cwd
    last_snapshot = WorkflowSnapshot(
        name=spec.meta.name,
        description=spec.meta.description,
    )

    # Everything below (worktree setup, manager/client construction) can raise.
    # It used to sit outside any try/finally: a failure here left the record
    # stuck at status="running" forever and leaked any manager/mailbox already
    # constructed. Route all setup failures through the same "interrupted"
    # checkpoint + cleanup path as run_workflow() failures below.
    manager = None
    mailbox = None
    try:
        if spec.policy.worktree == "on" or record.worktree_path:
            try:
                # Offload the synchronous git shell-out so a slow worktree add
                # doesn't stall this process's event loop for other tasks/agents.
                info = await asyncio.to_thread(
                    ensure_run_worktree,
                    record.run_id,
                    workspace=project_cwd,
                    existing_path=record.worktree_path,
                    existing_branch=record.worktree_branch,
                )
            except WorkflowWorktreeError as exc:
                release_run_lease(run_id, lease_token, workspace=project_cwd)
                return TaskExecutionResult(summary="", error=str(exc))
            record.worktree_path = str(info.path)
            record.worktree_branch = info.branch
            save_run(record, workspace=project_cwd)
            agent_cwd = info.path

        record.status = "running"
        record.error = None
        if record.task_id is None:
            record.task_id = task.id
        save_run(record, workspace=project_cwd)

        cfg = ConfigLoader().load()
        manager, mailbox = build_subagent_manager(cfg, agent_cwd)
        if manager is None:
            raise RuntimeError("workflow detach requires features.subagents=True")

        client = build_llm_client(cfg)
        _policy = (getattr(cfg, "approval_policy", None) or "on-request").strip().lower()
        loop_runtime = SubAgentRuntime(
            manager=manager,
            client=client,
            model=task.model or cfg.default_text_model or "deepseek-chat",
            config=cfg,
            workspace=agent_cwd,
            allow_shell=task.allow_shell,
            auto_approve=_policy in ("auto", "never-ask", "yolo"),
            task_manager=task.task_manager,
            cancel_token=cancel,
            mailbox=mailbox,
            active_task_id=task.id,
        )
        manager.attach_loop_runtime(loop_runtime)
        manager.attach_parent_cancel(cancel)

        runner = DeepSeekAgentRunner(
            manager,
            loop_runtime,
            parent_depth=0,
            workspace=agent_cwd,
        )
    except Exception as exc:  # noqa: BLE001 — setup failures must not leave the record stuck "running"
        safe_checkpoint_run(
            record,
            completed_step_ids=list(record.completed_step_ids),
            outputs=record.restored_outputs(),
            snapshot=last_snapshot,
            logs=list(record.logs),
            status="interrupted",
            error=str(exc),
            workspace=project_cwd,
        )
        if manager is not None:
            try:
                await manager.shutdown()
            except Exception:  # noqa: BLE001
                pass
        if mailbox is not None:
            try:
                mailbox.close()
            except Exception:  # noqa: BLE001
                pass
        release_run_lease(run_id, lease_token, workspace=project_cwd)
        return TaskExecutionResult(
            summary="",
            error=str(exc),
            detail=json.dumps({"run_id": record.run_id, "status": "interrupted"}),
        )

    skip_step_ids = set(record.completed_step_ids)
    initial_outputs = record.restored_outputs()

    def on_checkpoint(ctx_obj: Any, snap: WorkflowSnapshot, logs: list[str]) -> None:
        nonlocal last_snapshot
        last_snapshot = snap
        heartbeat_run_lease(run_id, lease_token, workspace=project_cwd)
        safe_checkpoint_run(
            record,
            completed_step_ids=list(ctx_obj.completed_step_ids),
            outputs=dict(ctx_obj.outputs),
            snapshot=snap,
            logs=logs,
            status="running",
            workspace=project_cwd,
        )

    try:
        result = await run_workflow(
            spec,
            runner=runner,
            cancel_event=cancel,
            manager=manager,
            on_checkpoint=on_checkpoint,
            task=record.task,
            initial_outputs=initial_outputs,
            skip_step_ids=skip_step_ids,
            cwd=project_cwd,
            run_id=record.run_id,
        )
    except WorkflowAbortedError:
        write_stop_intent(record.run_id, workspace=project_cwd)
        safe_checkpoint_run(
            record,
            completed_step_ids=list(record.completed_step_ids),
            outputs=record.restored_outputs(),
            snapshot=last_snapshot,
            logs=list(record.logs),
            status="cancelled",
            error="cancelled",
            workspace=project_cwd,
        )
        clear_stop_intent(record.run_id, workspace=project_cwd)
        return TaskExecutionResult(
            summary=f"Workflow {record.run_id} cancelled",
            error="cancelled",
            detail=json.dumps(
                {
                    "run_id": record.run_id,
                    "status": "cancelled",
                    "worktree_path": record.worktree_path,
                    "worktree_branch": record.worktree_branch,
                }
            ),
        )
    except WorkflowFailedError as exc:
        safe_checkpoint_run(
            record,
            completed_step_ids=list(record.completed_step_ids),
            outputs=record.restored_outputs(),
            snapshot=last_snapshot,
            logs=list(record.logs),
            status="failed",
            error=str(exc),
            workspace=project_cwd,
        )
        return TaskExecutionResult(
            summary=f"Workflow {record.run_id} failed",
            error=str(exc),
            detail=json.dumps({"run_id": record.run_id, "status": "failed"}),
        )
    except Exception as exc:  # noqa: BLE001 — surface to task record
        safe_checkpoint_run(
            record,
            completed_step_ids=list(record.completed_step_ids),
            outputs=record.restored_outputs(),
            snapshot=last_snapshot,
            logs=list(record.logs),
            status="interrupted",
            error=str(exc),
            workspace=project_cwd,
        )
        return TaskExecutionResult(
            summary="",
            error=str(exc),
            detail=json.dumps({"run_id": record.run_id, "status": "interrupted"}),
        )
    finally:
        try:
            await manager.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if mailbox is not None:
            try:
                mailbox.close()
            except Exception:  # noqa: BLE001
                pass
        # Release last so agent shutdown completes before another driver can
        # acquire: no new spawns can race our teardown.
        release_run_lease(run_id, lease_token, workspace=project_cwd)

    safe_checkpoint_run(
        record,
        completed_step_ids=list(record.completed_step_ids),
        outputs=record.restored_outputs(),
        snapshot=result.snapshot,
        logs=list(result.logs),
        status="completed",
        result=result.result,
        workspace=project_cwd,
    )
    clear_stop_intent(record.run_id, workspace=project_cwd)

    payload = {
        "run_id": record.run_id,
        "status": "completed",
        "worktree_path": record.worktree_path,
        "worktree_branch": record.worktree_branch,
        "result": result.result,
    }
    return TaskExecutionResult(
        summary=f"Workflow {record.run_id} completed",
        detail=json.dumps(payload, default=str),
    )
