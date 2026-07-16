"""Durable workflow run checkpoints for phase/step-level resume."""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

_LOG = logging.getLogger(__name__)

from deepseek_tui.config.paths import project_deepseek_dir
from deepseek_tui.utils import write_json_atomic
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


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
    # DAG / dynamic resume bags (optional; older run.json files omit these).
    runtime_graph: dict[str, Any] | None = None
    dynamic_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    budgets_used: dict[str, int] = field(default_factory=dict)
    generated_node_ids: list[str] = field(default_factory=list)
    skipped_step_ids: list[str] = field(default_factory=list)
    failed_step_ids: list[str] = field(default_factory=list)
    estimated_tokens_used: int = 0

    def parsed_spec(self) -> WorkflowSpec:
        return parse_workflow_spec(self.spec)

    def restored_outputs(self) -> dict[str, StepOutput]:
        return {
            sid: step_output_from_dict(raw)
            for sid, raw in self.outputs.items()
            if isinstance(raw, dict)
        }

    def resume_ctx_bag(self) -> dict[str, Any]:
        return {
            "skipped_step_ids": list(self.skipped_step_ids),
            "failed_step_ids": list(self.failed_step_ids),
            "dynamic_states": dict(self.dynamic_states),
            "budgets_used": dict(self.budgets_used),
            "generated_node_ids": list(self.generated_node_ids),
            "estimated_tokens_used": self.estimated_tokens_used,
        }


class WorkflowRunStoreError(WorkflowValidationError):
    pass


# A ``running`` run whose last checkpoint is newer than this is assumed to have
# a live driver right now (this process or another — e.g. a detached
# TaskManager job). Resuming it concurrently would duplicate agent spawns and
# race on ``run.json``. Prefer the file lease below when present; this
# updated_at heuristic remains a fallback for older runs / crashed holders.
ACTIVE_RUN_STALE_SECONDS = 300
# Lease heartbeat must be fresher than this (and owner pid alive) to block resume.
LEASE_STALE_SECONDS = 90


def lease_path(run_id: str, workspace: Path | None = None) -> Path:
    return workflow_runs_dir(workspace) / run_id / "lease.json"


def stop_intent_path(run_id: str, workspace: Path | None = None) -> Path:
    return workflow_runs_dir(workspace) / run_id / "stop-intent.json"


def write_stop_intent(
    run_id: str,
    *,
    reason: str = "cancelled",
    workspace: Path | None = None,
) -> Path:
    """Persist a durable stop request (survives process crash / restart)."""
    run_dir = workflow_runs_dir(workspace) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = stop_intent_path(run_id, workspace)
    write_json_atomic(
        path,
        {
            "run_id": run_id,
            "reason": reason,
            "requested_at": _utc_now(),
            "owner_pid": os.getpid(),
        },
    )
    return path


def clear_stop_intent(run_id: str, *, workspace: Path | None = None) -> None:
    path = stop_intent_path(run_id, workspace)
    try:
        path.unlink()
    except OSError:
        pass


def has_stop_intent(run_id: str, *, workspace: Path | None = None) -> bool:
    return stop_intent_path(run_id, workspace).is_file()


def read_stop_intent(
    run_id: str, *, workspace: Path | None = None
) -> dict[str, Any] | None:
    path = stop_intent_path(run_id, workspace)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it — treat as alive.
        return True
    except OSError:
        return False
    return True


def _lease_is_active(raw: dict[str, Any]) -> bool:
    hb = _parse_iso_utc(str(raw.get("heartbeat_at") or ""))
    if hb is None:
        return False
    age = (datetime.now(timezone.utc) - hb).total_seconds()
    if age >= LEASE_STALE_SECONDS:
        return False
    pid = raw.get("owner_pid")
    if not isinstance(pid, int):
        return False
    return _pid_alive(pid)


def is_run_actively_running(record: WorkflowRunRecord, *, workspace: Path | None = None) -> bool:
    """True if *record* looks like it still has a live driver right now."""
    path = lease_path(record.run_id, workspace)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict) and _lease_is_active(raw):
            return True
    if record.status != "running":
        return False
    updated = _parse_iso_utc(record.updated_at)
    if updated is None:
        return False
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    return age < ACTIVE_RUN_STALE_SECONDS


def acquire_run_lease(
    run_id: str,
    *,
    workspace: Path | None = None,
) -> str:
    """Acquire an exclusive run lease; return owner token.

    Uses ``fcntl.flock`` on Unix (project scope). Raises
    :class:`WorkflowRunStoreError` if another live holder exists.
    """
    import fcntl

    run_dir = workflow_runs_dir(workspace) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / "lease.lock"
    meta_path = run_dir / "lease.json"
    lock_fh = open(lock_path, "a+", encoding="utf-8")
    locked = False
    try:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise WorkflowRunStoreError(
                f"run {run_id} lease is held by another process"
            ) from exc
        if meta_path.is_file():
            try:
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = None
            if (
                isinstance(existing, dict)
                and _lease_is_active(existing)
                and existing.get("owner_pid") != os.getpid()
            ):
                raise WorkflowRunStoreError(
                    f"run {run_id} lease is held by pid={existing.get('owner_pid')}"
                )
        token = uuid.uuid4().hex
        payload = {
            "run_id": run_id,
            "owner_pid": os.getpid(),
            "owner_token": token,
            "heartbeat_at": _utc_now(),
        }
        write_json_atomic(meta_path, payload)
        # Keep flock for process lifetime via module-level registry.
        _LEASE_LOCKS[run_id] = lock_fh
        locked = False  # ownership transferred to registry
        return token
    except Exception:
        if locked:
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        if run_id not in _LEASE_LOCKS:
            try:
                lock_fh.close()
            except OSError:
                pass
        raise


_LEASE_LOCKS: dict[str, Any] = {}


def heartbeat_run_lease(
    run_id: str,
    token: str,
    *,
    workspace: Path | None = None,
) -> None:
    meta_path = lease_path(run_id, workspace)
    if not meta_path.is_file():
        return
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict) or raw.get("owner_token") != token:
        return
    raw["heartbeat_at"] = _utc_now()
    raw["owner_pid"] = os.getpid()
    write_json_atomic(meta_path, raw)


def release_run_lease(
    run_id: str,
    token: str,
    *,
    workspace: Path | None = None,
) -> None:
    import fcntl

    meta_path = lease_path(run_id, workspace)
    if meta_path.is_file():
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict) and raw.get("owner_token") == token:
            try:
                meta_path.unlink()
            except OSError:
                pass
    lock_fh = _LEASE_LOCKS.pop(run_id, None)
    if lock_fh is not None:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            lock_fh.close()
        except OSError:
            pass


@contextmanager
def hold_run_lease(
    run_id: str,
    *,
    workspace: Path | None = None,
) -> Iterator[str]:
    """Context manager: acquire → yield token → release."""
    token = acquire_run_lease(run_id, workspace=workspace)
    try:
        yield token
    finally:
        release_run_lease(run_id, token, workspace=workspace)


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
    """Persist ``run.json`` atomically (crash-safe write-tmp + rename)."""
    record.updated_at = _utc_now()
    path = run_path(record.run_id, workspace)
    write_json_atomic(path, asdict(record))
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
        runtime_graph=(
            raw["runtime_graph"]
            if isinstance(raw.get("runtime_graph"), dict)
            else None
        ),
        dynamic_states=(
            dict(raw["dynamic_states"])
            if isinstance(raw.get("dynamic_states"), dict)
            else {}
        ),
        budgets_used={
            str(k): int(v)
            for k, v in (raw.get("budgets_used") or {}).items()
            if isinstance(v, int)
        },
        generated_node_ids=[
            str(x) for x in (raw.get("generated_node_ids") or []) if isinstance(x, str)
        ],
        skipped_step_ids=[
            str(x) for x in (raw.get("skipped_step_ids") or []) if isinstance(x, str)
        ],
        failed_step_ids=[
            str(x) for x in (raw.get("failed_step_ids") or []) if isinstance(x, str)
        ],
        estimated_tokens_used=(
            int(raw["estimated_tokens_used"])
            if isinstance(raw.get("estimated_tokens_used"), int)
            else 0
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
    runtime_graph: dict[str, Any] | None = None,
    dynamic_states: dict[str, dict[str, Any]] | None = None,
    budgets_used: dict[str, int] | None = None,
    generated_node_ids: list[str] | None = None,
    skipped_step_ids: list[str] | None = None,
    failed_step_ids: list[str] | None = None,
    estimated_tokens_used: int | None = None,
) -> WorkflowRunRecord:
    record.completed_step_ids = list(completed_step_ids)
    record.outputs = {sid: step_output_to_dict(out) for sid, out in outputs.items()}
    record.snapshot = snapshot_to_dict(snapshot)
    record.logs = list(logs)
    record.status = status
    record.result = result
    record.error = error
    if runtime_graph is not None:
        record.runtime_graph = runtime_graph
    if dynamic_states is not None:
        record.dynamic_states = dict(dynamic_states)
    if budgets_used is not None:
        record.budgets_used = dict(budgets_used)
    if generated_node_ids is not None:
        record.generated_node_ids = list(generated_node_ids)
    if skipped_step_ids is not None:
        record.skipped_step_ids = list(skipped_step_ids)
    if failed_step_ids is not None:
        record.failed_step_ids = list(failed_step_ids)
    if estimated_tokens_used is not None:
        record.estimated_tokens_used = estimated_tokens_used
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
    runtime_graph: dict[str, Any] | None = None,
    dynamic_states: dict[str, dict[str, Any]] | None = None,
    budgets_used: dict[str, int] | None = None,
    generated_node_ids: list[str] | None = None,
    skipped_step_ids: list[str] | None = None,
    failed_step_ids: list[str] | None = None,
    estimated_tokens_used: int | None = None,
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
            runtime_graph=runtime_graph,
            dynamic_states=dynamic_states,
            budgets_used=budgets_used,
            generated_node_ids=generated_node_ids,
            skipped_step_ids=skipped_step_ids,
            failed_step_ids=failed_step_ids,
            estimated_tokens_used=estimated_tokens_used,
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
    from deepseek_tui.workflow.dag import step_to_dict

    base: dict[str, Any] = {
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
    }
    # v2 always keeps a phases convenience view after parse — prefer the
    # compiled graph so edges / dynamic roots survive create_run → resume.
    if spec.version >= 2 and spec.compiled_graph is not None:
        graph = spec.compiled_graph
        base["graph"] = {
            "nodes": [step_to_dict(step) for step in graph.nodes.values()],
            "edges": [{"from": e.from_id, "to": e.to_id} for e in graph.edges],
        }
        return base
    if spec.phases:
        base["phases"] = [
            {
                "id": phase.id,
                "title": phase.title,
                "steps": [step_to_dict(s) for s in phase.steps],
            }
            for phase in spec.phases
        ]
        return base
    raise WorkflowValidationError("cannot serialize workflow without phases or graph")
