"""Task record (de)serialization and on-disk state loading.

Persists each task as its own JSON file under ``./.deepseek/tasks/`` and a
queue in ``queue.json`` so tasks survive process restarts.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.tools.task.models import (
    CURRENT_TASK_SCHEMA_VERSION,
    STALE_RESTART_ERROR,
    STALE_RUNNING_TASK_SECONDS,
    TaskArtifactRef,
    TaskAttemptRecord,
    TaskChecklistItem,
    TaskChecklistState,
    TaskGateRecord,
    TaskGithubEvent,
    TaskRecord,
    TaskStatus,
    TaskTimelineEntry,
    TaskToolCallSummary,
    TaskToolStatus,
)


def _utc_now_iso() -> str:
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


def _is_stale_running_task(task: TaskRecord) -> bool:
    started = _parse_iso_utc(task.started_at)
    if started is None:
        return False
    age = (datetime.now(timezone.utc) - started).total_seconds()
    return age > STALE_RUNNING_TASK_SECONDS


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    delta = end - start
    millis = int(delta.total_seconds() * 1000)
    return max(0, millis)

def _resolve_task_id(tasks: dict[str, TaskRecord], id_or_prefix: str) -> str:
    """Resolve a task id or unique prefix to a full id."""
    if id_or_prefix in tasks:
        return id_or_prefix
    matches = [tid for tid in tasks if tid.startswith(id_or_prefix)]
    if len(matches) == 0:
        raise KeyError(f"Task not found: {id_or_prefix}")
    if len(matches) > 1:
        raise KeyError(
            f"Ambiguous task prefix '{id_or_prefix}': matches {len(matches)} tasks"
        )
    return matches[0]


def _task_record_to_dict(task: TaskRecord) -> dict[str, Any]:
    data = asdict(task)
    data["status"] = task.status.value
    for call in data.get("tool_calls", []):
        if isinstance(call.get("status"), TaskToolStatus):
            call["status"] = call["status"].value
    return data


def _task_record_from_dict(data: dict[str, Any]) -> TaskRecord:
    status = TaskStatus(data["status"])
    checklist_data = data.get("checklist") or {}
    checklist_items_raw = checklist_data.get("items", [])
    checklist = TaskChecklistState(
        items=[TaskChecklistItem(**item) for item in checklist_items_raw],
        completion_pct=checklist_data.get("completion_pct", 0),
        in_progress_id=checklist_data.get("in_progress_id"),
        updated_at=checklist_data.get("updated_at"),
    )
    gates = [TaskGateRecord(**g) for g in data.get("gates", [])]
    attempts = [TaskAttemptRecord(**a) for a in data.get("attempts", [])]
    artifacts = [TaskArtifactRef(**a) for a in data.get("artifacts", [])]
    github_events = [TaskGithubEvent(**e) for e in data.get("github_events", [])]
    tool_calls_raw = data.get("tool_calls", [])
    tool_calls = []
    for item in tool_calls_raw:
        status_val = item["status"]
        if isinstance(status_val, str):
            item = {**item, "status": TaskToolStatus(status_val)}
        tool_calls.append(TaskToolCallSummary(**item))
    timeline = [TaskTimelineEntry(**entry) for entry in data.get("timeline", [])]

    return TaskRecord(
        schema_version=data.get("schema_version", CURRENT_TASK_SCHEMA_VERSION),
        id=data["id"],
        prompt=data["prompt"],
        model=data["model"],
        workspace=data["workspace"],
        mode=data["mode"],
        allow_shell=data["allow_shell"],
        trust_mode=data["trust_mode"],
        auto_approve=data.get("auto_approve", False),
        status=status,
        created_at=data["created_at"],
        started_at=data.get("started_at"),
        ended_at=data.get("ended_at"),
        duration_ms=data.get("duration_ms"),
        result_summary=data.get("result_summary"),
        result_detail_path=data.get("result_detail_path"),
        error=data.get("error"),
        thread_id=data.get("thread_id"),
        turn_id=data.get("turn_id"),
        runtime_event_count=data.get("runtime_event_count", 0),
        checklist=checklist,
        gates=gates,
        attempts=attempts,
        artifacts=artifacts,
        github_events=github_events,
        tool_calls=tool_calls,
        timeline=timeline,
    )


def _load_state(
    tasks_dir: Path, queue_path: Path
) -> tuple[dict[str, TaskRecord], deque[str]]:
    """Load persisted tasks + queue, converting Running → Queued on recovery."""
    tasks: dict[str, TaskRecord] = {}
    if tasks_dir.exists():
        for path in sorted(tasks_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            task = _task_record_from_dict(data)
            if task.schema_version > CURRENT_TASK_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Task schema v{task.schema_version} is newer than supported"
                    f" v{CURRENT_TASK_SCHEMA_VERSION}"
                )
            if task.status is TaskStatus.RUNNING:
                if _is_stale_running_task(task):
                    now = _utc_now_iso()
                    task.status = TaskStatus.FAILED
                    task.started_at = task.started_at
                    task.ended_at = now
                    task.error = STALE_RESTART_ERROR
                    task.timeline.append(
                        TaskTimelineEntry(
                            timestamp=now,
                            kind="failed",
                            summary="Stale running task marked failed on recovery",
                        )
                    )
                else:
                    task.status = TaskStatus.QUEUED
                    task.started_at = None
                    task.ended_at = None
                    task.duration_ms = None
                    task.timeline.append(
                        TaskTimelineEntry(
                            timestamp=_utc_now_iso(),
                            kind="recovered",
                            summary="Recovered from restart and re-queued",
                        )
                    )
            # Safety: if a queued task points at a workspace that no longer
            # exists on disk (common with pytest temp dirs or moved
            # projects), fail it immediately instead of looping forever on
            # restart. Without this guard, zombie tasks from old test runs
            # spawn an Engine per worker tick and starve the event loop.
            if task.status is TaskStatus.QUEUED:
                ws = task.workspace
                if ws and not Path(ws).exists():
                    now = _utc_now_iso()
                    task.status = TaskStatus.FAILED
                    task.error = f"workspace not found: {ws}"
                    task.ended_at = now
                    task.timeline.append(
                        TaskTimelineEntry(
                            timestamp=now,
                            kind="failed",
                            summary=f"workspace not found: {ws}",
                        )
                    )
            tasks[task.id] = task

    queue: deque[str] = deque()
    if queue_path.exists():
        with queue_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        queue = deque(data.get("queue", []))

    queue = deque(
        tid for tid in queue if tid in tasks and tasks[tid].status is TaskStatus.QUEUED
    )
    known = set(queue)
    missing = sorted(
        tid
        for tid, task in tasks.items()
        if task.status is TaskStatus.QUEUED and tid not in known
    )
    for tid in missing:
        queue.append(tid)
    return tasks, queue


def _write_json_atomic(path: Path, value: Any) -> None:
    from deepseek_tui.utils import write_json_atomic

    write_json_atomic(path, value)
