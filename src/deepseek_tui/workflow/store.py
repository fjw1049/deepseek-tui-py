"""Durable workflow run checkpoints for phase/step-level resume."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_LOG = logging.getLogger(__name__)

from deepseek_tui.config.paths import project_deepseek_dir
from deepseek_tui.workflow.models import (
    StepOutput,
    WorkflowSnapshot,
    WorkflowSpec,
    WorkflowValidationError,
    parse_workflow_spec,
    snapshot_to_dict,
    step_output_from_dict,
    step_output_to_dict,
)

WorkflowRunStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
    "timed_out",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return f"wf_{uuid.uuid4().hex[:12]}"


def workflow_runs_dir(workspace: Path | None = None) -> Path:
    """``<cwd>/.deepseek/workflow-runs/``."""
    return project_deepseek_dir(workspace) / "workflow-runs"


@dataclass
class WorkflowRunRecord:
    run_id: str
    status: WorkflowRunStatus
    spec: dict[str, Any]
    task: str = ""
    completed_step_ids: list[str] = field(default_factory=list)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    snapshot: dict[str, Any] | None = None
    result: Any = None
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    worktree_path: str | None = None
    worktree_branch: str | None = None
    task_id: str | None = None

    def parsed_spec(self) -> WorkflowSpec:
        return parse_workflow_spec(self.spec)

    def restored_outputs(self) -> dict[str, StepOutput]:
        return {
            sid: step_output_from_dict(raw)
            for sid, raw in self.outputs.items()
            if isinstance(raw, dict)
        }


class WorkflowRunStoreError(WorkflowValidationError):
    pass


def run_path(run_id: str, workspace: Path | None = None) -> Path:
    return workflow_runs_dir(workspace) / run_id / "run.json"


def create_run(
    spec: WorkflowSpec,
    *,
    task: str = "",
    workspace: Path | None = None,
    run_id: str | None = None,
) -> WorkflowRunRecord:
    rid = run_id or new_run_id()
    now = _utc_now()
    record = WorkflowRunRecord(
        run_id=rid,
        status="running",
        spec=_spec_to_dict(spec),
        task=task or "",
        created_at=now,
        updated_at=now,
    )
    save_run(record, workspace=workspace)
    return record


def save_run(record: WorkflowRunRecord, *, workspace: Path | None = None) -> Path:
    """Persist ``run.json`` via temp file + ``os.replace`` (crash-safe)."""
    record.updated_at = _utc_now()
    path = run_path(record.run_id, workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(record)
    data = json.dumps(payload, indent=2, default=str)
    # Unique tmp avoids colliding writers briefly stomping the same name.
    tmp = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        raise
    return path


def load_run(run_id: str, *, workspace: Path | None = None) -> WorkflowRunRecord:
    path = run_path(run_id, workspace)
    if not path.is_file():
        # Allow unique prefix match
        root = workflow_runs_dir(workspace)
        if root.is_dir():
            matches = [
                p
                for p in root.iterdir()
                if p.is_dir() and p.name.startswith(run_id) and (p / "run.json").is_file()
            ]
            if len(matches) == 1:
                path = matches[0] / "run.json"
            elif len(matches) > 1:
                raise WorkflowRunStoreError(f"ambiguous run id prefix: {run_id!r}")
        if not path.is_file():
            raise WorkflowRunStoreError(f"workflow run not found: {run_id!r}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowRunStoreError(f"cannot read run {run_id}: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkflowRunStoreError(f"invalid run file for {run_id}")
    return WorkflowRunRecord(
        run_id=str(raw.get("run_id") or run_id),
        status=raw.get("status") or "interrupted",  # type: ignore[arg-type]
        spec=raw.get("spec") if isinstance(raw.get("spec"), dict) else {},
        task=str(raw.get("task") or ""),
        completed_step_ids=list(raw.get("completed_step_ids") or []),
        outputs=dict(raw.get("outputs") or {}),
        snapshot=raw.get("snapshot") if isinstance(raw.get("snapshot"), dict) else None,
        result=raw.get("result"),
        logs=list(raw.get("logs") or []),
        error=raw.get("error"),
        created_at=str(raw.get("created_at") or ""),
        updated_at=str(raw.get("updated_at") or ""),
        worktree_path=(
            str(raw["worktree_path"])
            if isinstance(raw.get("worktree_path"), str) and raw["worktree_path"]
            else None
        ),
        worktree_branch=(
            str(raw["worktree_branch"])
            if isinstance(raw.get("worktree_branch"), str) and raw["worktree_branch"]
            else None
        ),
        task_id=(
            str(raw["task_id"])
            if isinstance(raw.get("task_id"), str) and raw["task_id"]
            else None
        ),
    )


def list_runs(
    *,
    workspace: Path | None = None,
    limit: int = 20,
) -> list[WorkflowRunRecord]:
    root = workflow_runs_dir(workspace)
    if not root.is_dir():
        return []
    records: list[WorkflowRunRecord] = []
    for child in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        try:
            records.append(load_run(child.name, workspace=workspace))
        except WorkflowRunStoreError:
            continue
        if len(records) >= limit:
            break
    return records


def checkpoint_run(
    record: WorkflowRunRecord,
    *,
    completed_step_ids: list[str],
    outputs: dict[str, StepOutput],
    snapshot: WorkflowSnapshot,
    logs: list[str],
    status: WorkflowRunStatus = "running",
    result: Any = None,
    error: str | None = None,
    workspace: Path | None = None,
) -> WorkflowRunRecord:
    record.completed_step_ids = list(completed_step_ids)
    record.outputs = {sid: step_output_to_dict(out) for sid, out in outputs.items()}
    record.snapshot = snapshot_to_dict(snapshot)
    record.logs = list(logs)
    record.status = status
    record.result = result
    record.error = error
    save_run(record, workspace=workspace)
    return record


def safe_checkpoint_run(
    record: WorkflowRunRecord,
    *,
    completed_step_ids: list[str],
    outputs: dict[str, StepOutput],
    snapshot: WorkflowSnapshot,
    logs: list[str],
    status: WorkflowRunStatus = "running",
    result: Any = None,
    error: str | None = None,
    workspace: Path | None = None,
) -> bool:
    """Like :func:`checkpoint_run`, but never raises — returns False on failure.

    Checkpoint I/O must not mask the original workflow error (disk full,
    permissions, etc.). Callers should log via the returned flag / logger.
    """
    try:
        checkpoint_run(
            record,
            completed_step_ids=completed_step_ids,
            outputs=outputs,
            snapshot=snapshot,
            logs=logs,
            status=status,
            result=result,
            error=error,
            workspace=workspace,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — persistence must not abort the run path
        _LOG.warning(
            "workflow checkpoint failed for %s (status=%s): %s",
            record.run_id,
            status,
            exc,
            exc_info=True,
        )
        return False


def _spec_to_dict(spec: WorkflowSpec) -> dict[str, Any]:
    """Serialize a validated spec back to IR JSON (lossy for unknown fields)."""
    from deepseek_tui.workflow.models import FanoutStep, LoopStep, PipelineStep

    def step_dict(step: Any) -> dict[str, Any]:
        if step.type == "agent":
            return {
                "id": step.id,
                "type": "agent",
                "label": step.label,
                "agent_type": step.agent_type,
                "model": step.model,
                "allowed_tools": step.allowed_tools,
                "prompt": step.prompt,
                "output_schema": step.output_schema,
            }
        if step.type == "fanout":
            assert isinstance(step, FanoutStep)
            data: dict[str, Any] = {
                "id": step.id,
                "type": "fanout",
                "concurrency": step.concurrency,
                "agent": {
                    "label": step.agent.label,
                    "label_template": step.agent.label_template,
                    "agent_type": step.agent.agent_type,
                    "model": step.agent.model,
                    "allowed_tools": step.agent.allowed_tools,
                    "prompt": step.agent.prompt,
                    "prompt_template": step.agent.prompt_template,
                    "output_schema": step.agent.output_schema,
                },
            }
            if step.items is not None:
                data["items"] = step.items
            if step.items_from is not None:
                data["items_from"] = {
                    "step": step.items_from.step,
                    "path": step.items_from.path,
                }
            return data
        if step.type == "pipeline":
            assert isinstance(step, PipelineStep)
            return {
                "id": step.id,
                "type": "pipeline",
                "items": step.items,
                "stages": [
                    {
                        "label_template": st.label_template,
                        "agent_type": st.agent_type,
                        "model": st.model,
                        "prompt_template": st.prompt_template,
                    }
                    for st in step.stages
                ],
            }
        if step.type == "synthesis":
            return {
                "id": step.id,
                "type": "synthesis",
                "label": step.label,
                "agent_type": step.agent_type,
                "model": step.model,
                "allowed_tools": step.allowed_tools,
                "prompt_template": step.prompt_template,
                "output_schema": step.output_schema,
            }
        if step.type == "loop":
            assert isinstance(step, LoopStep)
            until = None
            if step.until is not None:
                until = {
                    "path": step.until.path,
                    "equals": step.until.equals,
                    "step": step.until.step,
                }
            return {
                "id": step.id,
                "type": "loop",
                "max_rounds": step.max_rounds,
                "until": until,
                "steps": [step_dict(s) for s in step.steps],
            }
        raise WorkflowRunStoreError(f"unknown step type for serialize: {step.type}")

    return {
        "version": spec.version,
        "meta": {"name": spec.meta.name, "description": spec.meta.description},
        "policy": {
            "approval_mode": spec.policy.approval_mode,
            "on_error": spec.policy.on_error,
            "max_agents": spec.policy.max_agents,
            "concurrency": spec.policy.concurrency,
            "wall_clock_seconds": spec.policy.wall_clock_seconds,
            "token_budget": spec.policy.token_budget,
            "worktree": spec.policy.worktree,
        },
        "phases": [
            {
                "id": phase.id,
                "title": phase.title,
                "steps": [step_dict(s) for s in phase.steps],
            }
            for phase in spec.phases
        ],
    }
