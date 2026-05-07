"""Durable task manager.

Mirrors `crates/tui/src/task_manager.rs` (1,845 lines). Persists each task as
its own JSON file under ``~/.deepseek/tasks/`` and maintains a queue in
``queue.json`` so tasks survive process restarts.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

CURRENT_TASK_SCHEMA_VERSION = 1
TIMELINE_SUMMARY_LIMIT = 280
MAX_WORKERS = 4


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    def is_terminal(self) -> bool:
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED)


class TaskToolStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(slots=True)
class TaskTimelineEntry:
    timestamp: str
    kind: str
    summary: str
    detail_path: str | None = None


@dataclass(slots=True)
class TaskToolCallSummary:
    id: str
    name: str
    status: TaskToolStatus
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    detail_path: str | None = None
    patch_ref: str | None = None


@dataclass(slots=True)
class TaskChecklistItem:
    id: int
    content: str
    status: str


@dataclass(slots=True)
class TaskChecklistState:
    items: list[TaskChecklistItem] = field(default_factory=list)
    completion_pct: int = 0
    in_progress_id: int | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class TaskGateRecord:
    id: str
    gate: str
    command: str
    cwd: str
    exit_code: int | None
    status: str
    classification: str
    duration_ms: int
    summary: str
    recorded_at: str
    log_path: str | None = None


@dataclass(slots=True)
class TaskAttemptRecord:
    id: str
    attempt_group_id: str
    attempt_index: int
    attempt_count: int
    summary: str
    changed_files: list[str]
    verification: list[str]
    selected: bool
    recorded_at: str
    base_ref: str | None = None
    base_sha: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    patch_path: str | None = None


@dataclass(slots=True)
class TaskArtifactRef:
    label: str
    path: str
    summary: str
    created_at: str


@dataclass(slots=True)
class TaskGithubEvent:
    id: str
    action: str
    target: str
    number: int
    summary: str
    recorded_at: str
    url: str | None = None


@dataclass(slots=True)
class TaskRecord:
    schema_version: int
    id: str
    prompt: str
    model: str
    workspace: str
    mode: str
    allow_shell: bool
    trust_mode: bool
    auto_approve: bool
    status: TaskStatus
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    result_summary: str | None = None
    result_detail_path: str | None = None
    error: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    runtime_event_count: int = 0
    checklist: TaskChecklistState = field(default_factory=TaskChecklistState)
    gates: list[TaskGateRecord] = field(default_factory=list)
    attempts: list[TaskAttemptRecord] = field(default_factory=list)
    artifacts: list[TaskArtifactRef] = field(default_factory=list)
    github_events: list[TaskGithubEvent] = field(default_factory=list)
    tool_calls: list[TaskToolCallSummary] = field(default_factory=list)
    timeline: list[TaskTimelineEntry] = field(default_factory=list)

    def summary(self) -> TaskSummary:
        return TaskSummary(
            id=self.id,
            status=self.status,
            prompt_summary=_summarize_text(self.prompt, TIMELINE_SUMMARY_LIMIT),
            model=self.model,
            mode=self.mode,
            created_at=self.created_at,
            started_at=self.started_at,
            ended_at=self.ended_at,
            duration_ms=self.duration_ms,
            error=self.error,
            thread_id=self.thread_id,
            turn_id=self.turn_id,
        )


@dataclass(slots=True)
class TaskSummary:
    id: str
    status: TaskStatus
    prompt_summary: str
    model: str
    mode: str
    created_at: str
    started_at: str | None
    ended_at: str | None
    duration_ms: int | None
    error: str | None
    thread_id: str | None
    turn_id: str | None


@dataclass(slots=True)
class TaskCounts:
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    canceled: int = 0


@dataclass(slots=True)
class NewTaskRequest:
    prompt: str
    model: str | None = None
    workspace: str | None = None
    mode: str | None = None
    allow_shell: bool | None = None
    trust_mode: bool | None = None
    auto_approve: bool | None = None


@dataclass(slots=True)
class TaskManagerConfig:
    data_dir: Path
    default_workspace: Path
    default_model: str = "deepseek-chat"
    default_mode: str = "agent"
    allow_shell: bool = False
    trust_mode: bool = False
    worker_count: int = 1
    max_subagents: int = 4


@dataclass(slots=True)
class ExecutionTask:
    id: str
    prompt: str
    model: str
    workspace: str
    mode_label: str
    allow_shell: bool
    trust_mode: bool
    auto_approve: bool


@dataclass(slots=True)
class TaskExecutionResult:
    summary: str
    detail: str | None = None
    error: str | None = None


ExecutorFunc = Callable[[ExecutionTask, asyncio.Event], Awaitable[TaskExecutionResult]]


def default_tasks_dir() -> Path:
    """Return the default task data directory.

    Mirrors Rust `default_tasks_dir()` (task_manager.rs:1629).
    """
    env = os.environ.get("DEEPSEEK_TASKS_DIR", "").strip()
    if env:
        return Path(env)
    home = Path.home()
    if home.exists():
        return home / ".deepseek" / "tasks"
    return Path(".deepseek") / "tasks"


async def _stub_executor(
    task: ExecutionTask, cancel: asyncio.Event
) -> TaskExecutionResult:
    """Placeholder executor: sleeps briefly, returns synthetic result.

    Integration debt: Stage 3.1.simplified: real TaskExecutor not wired.
    Replaced in a later stage when engine/turn_loop can drive task execution.
    """
    try:
        await asyncio.wait_for(cancel.wait(), timeout=0.05)
    except asyncio.TimeoutError:
        return TaskExecutionResult(
            summary=f"[stub] task '{task.prompt[:60]}' completed without real executor",
            detail=None,
            error=None,
        )
    return TaskExecutionResult(summary="", error="canceled")


class TaskManager:
    """Durable task manager.

    Mirrors Rust `TaskManager` (task_manager.rs:702-1472).
    """

    def __init__(
        self,
        cfg: TaskManagerConfig,
        executor: ExecutorFunc | None = None,
    ) -> None:
        self._cfg = cfg
        self._executor: ExecutorFunc = executor or _stub_executor
        self._tasks_dir = cfg.data_dir / "tasks"
        self._artifacts_dir = cfg.data_dir / "artifacts"
        self._queue_path = cfg.data_dir / "queue.json"
        self._tasks: dict[str, TaskRecord] = {}
        self._queue: deque[str] = deque()
        self._running_cancel: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._notify = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._worker_tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Initialize directories, load prior state, spawn workers."""
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

        tasks, queue = _load_state(self._tasks_dir, self._queue_path)
        self._tasks = tasks
        self._queue = queue

        async with self._lock:
            self._persist_all_locked()

        workers = max(1, min(self._cfg.worker_count, MAX_WORKERS))
        for _ in range(workers):
            self._worker_tasks.append(asyncio.create_task(self._worker_loop()))

    async def shutdown(self) -> None:
        self._shutdown.set()
        self._notify.set()
        for task in self._worker_tasks:
            task.cancel()
        for task in self._worker_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._worker_tasks.clear()

    def is_shutdown(self) -> bool:
        return self._shutdown.is_set()

    def data_dir(self) -> Path:
        return self._cfg.data_dir

    async def add_task(self, req: NewTaskRequest) -> TaskRecord:
        prompt = req.prompt.strip()
        if not prompt:
            raise ValueError("Task prompt cannot be empty")

        now = _utc_now_iso()
        task = TaskRecord(
            schema_version=CURRENT_TASK_SCHEMA_VERSION,
            id=f"task_{uuid.uuid4().hex[:8]}",
            prompt=prompt,
            model=req.model or self._cfg.default_model,
            workspace=str(
                Path(req.workspace) if req.workspace else self._cfg.default_workspace
            ),
            mode=req.mode or self._cfg.default_mode,
            allow_shell=(
                req.allow_shell if req.allow_shell is not None else self._cfg.allow_shell
            ),
            trust_mode=(
                req.trust_mode if req.trust_mode is not None else self._cfg.trust_mode
            ),
            auto_approve=req.auto_approve if req.auto_approve is not None else True,
            status=TaskStatus.QUEUED,
            created_at=now,
            timeline=[
                TaskTimelineEntry(
                    timestamp=now, kind="queued", summary="Task queued"
                )
            ],
        )

        async with self._lock:
            self._queue.append(task.id)
            self._tasks[task.id] = task
            self._persist_all_locked()
        self._notify.set()
        return task

    async def list_tasks(self, limit: int | None = None) -> list[TaskSummary]:
        async with self._lock:
            items = [record.summary() for record in self._tasks.values()]
        items.sort(key=lambda s: s.created_at, reverse=True)
        if limit is not None:
            items = items[:limit]
        return items

    async def get_task(self, id_or_prefix: str) -> TaskRecord:
        async with self._lock:
            task_id = _resolve_task_id(self._tasks, id_or_prefix)
            return self._tasks[task_id]

    async def cancel_task(self, id_or_prefix: str) -> TaskRecord:
        now = _utc_now_iso()
        token_to_cancel: asyncio.Event | None = None
        async with self._lock:
            task_id = _resolve_task_id(self._tasks, id_or_prefix)
            task = self._tasks[task_id]
            if task.status is TaskStatus.QUEUED:
                task.status = TaskStatus.CANCELED
                task.ended_at = now
                task.duration_ms = 0
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="canceled",
                        summary="Task canceled before execution",
                    )
                )
                self._queue = deque(q for q in self._queue if q != task_id)
            elif task.status is TaskStatus.RUNNING:
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="cancel_requested",
                        summary="Cancellation requested",
                    )
                )
                token_to_cancel = self._running_cancel.get(task_id)

            self._persist_all_locked()
            result = self._tasks[task_id]

        if token_to_cancel is not None:
            token_to_cancel.set()
        return result

    async def counts(self) -> TaskCounts:
        async with self._lock:
            counts = TaskCounts()
            for task in self._tasks.values():
                if task.status is TaskStatus.QUEUED:
                    counts.queued += 1
                elif task.status is TaskStatus.RUNNING:
                    counts.running += 1
                elif task.status is TaskStatus.COMPLETED:
                    counts.completed += 1
                elif task.status is TaskStatus.FAILED:
                    counts.failed += 1
                elif task.status is TaskStatus.CANCELED:
                    counts.canceled += 1
            return counts

    async def _worker_loop(self) -> None:
        while not self._shutdown.is_set():
            next_run = await self._pop_next_task()
            if next_run is None:
                try:
                    await asyncio.wait_for(self._notify.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                finally:
                    self._notify.clear()
                continue
            await self._run_task(*next_run)

    async def _pop_next_task(self) -> tuple[str, ExecutionTask, asyncio.Event] | None:
        async with self._lock:
            while self._queue:
                task_id = self._queue.popleft()
                task = self._tasks.get(task_id)
                if task is None or task.status is not TaskStatus.QUEUED:
                    self._persist_queue_locked()
                    continue
                now = _utc_now_iso()
                task.status = TaskStatus.RUNNING
                task.started_at = now
                task.ended_at = None
                task.duration_ms = None
                task.error = None
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now, kind="running", summary="Task started"
                    )
                )
                request = ExecutionTask(
                    id=task.id,
                    prompt=task.prompt,
                    model=task.model,
                    workspace=task.workspace,
                    mode_label=task.mode,
                    allow_shell=task.allow_shell,
                    trust_mode=task.trust_mode,
                    auto_approve=task.auto_approve,
                )
                cancel = asyncio.Event()
                self._running_cancel[task_id] = cancel
                self._persist_all_locked()
                return task_id, request, cancel
        return None

    async def _run_task(
        self, task_id: str, request: ExecutionTask, cancel: asyncio.Event
    ) -> None:
        result: TaskExecutionResult
        try:
            result = await self._executor(request, cancel)
        except Exception as exc:  # noqa: BLE001 -- translate all errors into task state
            result = TaskExecutionResult(summary="", error=str(exc))

        async with self._lock:
            self._running_cancel.pop(task_id, None)
            task = self._tasks.get(task_id)
            if task is None:
                return
            now = _utc_now_iso()
            task.ended_at = now
            if task.started_at is not None:
                task.duration_ms = _duration_ms(task.started_at, now)
            if cancel.is_set() and task.status is not TaskStatus.CANCELED:
                task.status = TaskStatus.CANCELED
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="canceled",
                        summary="Task canceled mid-run",
                    )
                )
            elif result.error:
                task.status = TaskStatus.FAILED
                task.error = result.error
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="failed",
                        summary=_summarize_text(result.error, TIMELINE_SUMMARY_LIMIT),
                    )
                )
            else:
                task.status = TaskStatus.COMPLETED
                task.result_summary = result.summary
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="completed",
                        summary=_summarize_text(result.summary, TIMELINE_SUMMARY_LIMIT),
                    )
                )
            self._persist_all_locked()

    def _persist_all_locked(self) -> None:
        self._persist_queue_locked()
        for task in self._tasks.values():
            self._persist_task_locked(task)

    def _persist_queue_locked(self) -> None:
        _write_json_atomic(self._queue_path, {"queue": list(self._queue)})

    def _persist_task_locked(self, task: TaskRecord) -> None:
        path = self._tasks_dir / f"{task.id}.json"
        _write_json_atomic(path, _task_record_to_dict(task))


# --- module-level helpers ------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    delta = end - start
    millis = int(delta.total_seconds() * 1000)
    return max(0, millis)


def _summarize_text(text: str, limit: int) -> str:
    take = max(0, limit - 3)
    out: list[str] = []
    count = 0
    for ch in text:
        if count >= take:
            out.append("...")
            return "".join(out)
        if ch.isprintable() is False and ch not in ("\n", "\t"):
            continue
        out.append(ch)
        count += 1
    return "".join(out)


def _resolve_task_id(tasks: dict[str, TaskRecord], id_or_prefix: str) -> str:
    """Resolve a task id or unique prefix to a full id.

    Mirrors Rust `resolve_task_id()` (task_manager.rs:1545-1563).
    """
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
        auto_approve=data.get("auto_approve", True),
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
    """Load persisted tasks + queue, converting Running → Queued on recovery.

    Mirrors Rust `load_state()` (task_manager.rs:1474-1543).
    """
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
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, sort_keys=False, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
