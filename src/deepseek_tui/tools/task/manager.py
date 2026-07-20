"""Durable TaskManager — queueing, workers, and lifecycle transitions."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from deepseek_tui.tools.task.models import (
    CRON_PROMPT_MARKER,
    CURRENT_TASK_SCHEMA_VERSION,
    MAX_WORKERS,
    TIMELINE_SUMMARY_LIMIT,
    _MAX_TERMINAL_IN_MEMORY,
    ExecutionTask,
    ExecutorFunc,
    NewTaskRequest,
    TaskArtifactRef,
    TaskChecklistItem,
    TaskChecklistState,
    TaskCounts,
    TaskExecutionResult,
    TaskGateRecord,
    TaskGithubEvent,
    TaskManagerConfig,
    TaskRecord,
    TaskStatus,
    TaskSummary,
    TaskTimelineEntry,
    _summarize_text,
)
from deepseek_tui.tools.task.store import (
    _duration_ms,
    _load_state,
    _resolve_task_id,
    _task_record_from_dict,
    _task_record_to_dict,
    _utc_now_iso,
    _write_json_atomic,
)


async def _stub_executor(
    task: ExecutionTask, cancel: asyncio.Event
) -> TaskExecutionResult:
    """Placeholder executor: sleeps briefly, returns synthetic result.

    Integration debt: Stage 3.1.simplified: real TaskExecutor not wired.
    Use ``real_task_executor`` from ``engine.executors`` for production.
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


def get_real_task_executor() -> ExecutorFunc:
    """Return the real task executor that drives Engine turn loops."""
    from deepseek_tui.engine.dispatch import real_task_executor
    from deepseek_tui.workflow.detach import wrap_task_executor_for_workflow_detach

    return wrap_task_executor_for_workflow_detach(real_task_executor)


class TaskManager:
    """Durable task manager."""

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
        for token in self._running_cancel.values():
            token.set()
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

    def running_count(self) -> int:
        """Count queued + running durable tasks (for session activity UI)."""
        return sum(
            1
            for t in self._tasks.values()
            if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)
        )

    def data_dir(self) -> Path:
        return self._cfg.data_dir

    def artifact_absolute_path(self, patch_ref: str) -> Path:
        """Resolve a recorded artifact reference to an absolute path."""
        p = Path(patch_ref)
        if p.is_absolute():
            return p
        return self._cfg.data_dir / p

    def write_task_artifact(
        self, task_id: str, label: str, content: str
    ) -> Path:
        """Write a durable task artifact and return the persisted relative path."""
        artifact_dir = self._artifacts_dir / task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stamp = _utc_now_iso().replace(":", "").replace("-", "")
        safe_label = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        if not safe_label:
            safe_label = "artifact"
        filename = f"{stamp}_{safe_label}.txt"
        absolute = artifact_dir / filename
        absolute.write_text(content, encoding="utf-8")
        try:
            return absolute.relative_to(self._cfg.data_dir)
        except ValueError:
            return absolute

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
            auto_approve=req.auto_approve if req.auto_approve is not None else False,
            status=TaskStatus.QUEUED,
            created_at=now,
            thread_id=req.thread_id,
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

    async def list_tasks(
        self,
        limit: int | None = None,
        *,
        since: str | None = None,
    ) -> list[TaskSummary]:
        """List durable tasks (newest first).

        ``since`` is an ISO-8601 timestamp; tasks with ``created_at <
        since`` are filtered out. Callers like the right info-sidebar
        use this to avoid surfacing stale `failed` records from prior
        TUI sessions every time the user opens a fresh chat (issue
        triaged 2026-05-12 — fresh "hello" was lighting up the panel
        with last week's pytest-failed tasks).
        """
        async with self._lock:
            items = [record.summary() for record in self._tasks.values()]
        if since is not None:
            items = [s for s in items if s.created_at >= since]
        items.sort(key=lambda s: s.created_at, reverse=True)
        if limit is not None:
            items = items[:limit]
        return items

    async def get_task(self, id_or_prefix: str) -> TaskRecord:
        async with self._lock:
            try:
                task_id = _resolve_task_id(self._tasks, id_or_prefix)
                return self._tasks[task_id]
            except KeyError:
                pass
            task = self._reload_task_from_disk(id_or_prefix)
            if task is not None:
                return task
            raise KeyError(f"Task not found: {id_or_prefix}")

    def _reload_task_from_disk(self, id_or_prefix: str) -> TaskRecord | None:
        for path in self._tasks_dir.glob("*.json"):
            tid = path.stem
            if tid == id_or_prefix or tid.startswith(id_or_prefix):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    task = _task_record_from_dict(data)
                    self._tasks[task.id] = task
                    return task
                except (OSError, json.JSONDecodeError, KeyError):
                    continue
        return None

    async def resume_task(self, id_or_prefix: str) -> TaskRecord:
        """Re-queue a resumable terminal task for transcript (or detach) resume.

        Clears sticky error and appends a timeline entry. Detach jobs keep
        relying on Workflow checkpoints; plain tasks hydrate transcripts in
        the executor.
        """
        now = _utc_now_iso()
        async with self._lock:
            task_id = _resolve_task_id(self._tasks, id_or_prefix)
            task = self._tasks[task_id]
            if task.status is TaskStatus.RUNNING or task.status is TaskStatus.QUEUED:
                raise RuntimeError(
                    f"Task {task_id} is already {task.status.value}"
                )
            if not task.status.is_resumable():
                raise RuntimeError(
                    f"Task {task_id} status={task.status.value} cannot be resumed"
                )
            task.status = TaskStatus.QUEUED
            task.error = None
            task.ended_at = None
            task.duration_ms = None
            task.result_summary = None
            if task_id not in self._queue:
                self._queue.append(task_id)
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=now,
                    kind="resumed",
                    summary="Task re-queued for resume from checkpoint",
                )
            )
            self._persist_all_locked()
            result = task
        self._notify.set()
        return result

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

    async def record_tool_metadata(
        self, id_or_prefix: str, metadata: dict[str, Any]
    ) -> TaskRecord | None:
        """Apply ``task_updates`` from a tool's result metadata to the task.

        Currently honors the
        ``task_updates.checklist`` key — see
        :meth:`_apply_task_update_metadata` for details. Returns the
        updated record, or ``None`` if the task no longer exists (e.g.
        was cancelled and removed between events).

        Tools call this via the side-channel set up by
        :class:`real_task_executor`: ``ToolContext.metadata`` carries a
        ``task_manager`` reference + ``task_id``; the checklist tools
        invoke ``manager.record_tool_metadata(task_id, metadata)`` after
        every successful write. Quiet no-op when ``task_updates`` is
        missing so non-checklist tools don't have to opt out.
        """
        if not isinstance(metadata, dict):
            return None
        if "task_updates" not in metadata:
            return None
        async with self._lock:
            try:
                task_id = _resolve_task_id(self._tasks, id_or_prefix)
            except KeyError:
                return None
            task = self._tasks.get(task_id)
            if task is None:
                return None
            self._apply_task_update_metadata(task, metadata)
            self._persist_task_locked(task)
            return task

    def _apply_task_update_metadata(
        self, task: TaskRecord, metadata: dict[str, Any]
    ) -> None:
        """Translate ``task_updates`` payload into ``TaskRecord`` mutations."""
        updates = metadata.get("task_updates")
        if not isinstance(updates, dict):
            return
        now = _utc_now_iso()

        checklist_payload = updates.get("checklist")
        if isinstance(checklist_payload, dict):
            items_raw = checklist_payload.get("items", [])
            items: list[TaskChecklistItem] = []
            if isinstance(items_raw, list):
                for entry in items_raw:
                    if not isinstance(entry, dict):
                        continue
                    raw_id = entry.get("id")
                    try:
                        item_id = int(raw_id) if raw_id is not None else 0
                    except (TypeError, ValueError):
                        continue
                    items.append(
                        TaskChecklistItem(
                            id=item_id,
                            content=str(entry.get("content", "")),
                            status=str(entry.get("status", "pending")),
                        )
                    )
            try:
                completion_pct = int(checklist_payload.get("completion_pct", 0))
            except (TypeError, ValueError):
                completion_pct = 0
            in_progress_raw = checklist_payload.get("in_progress_id")
            in_progress_id = (
                int(in_progress_raw)
                if isinstance(in_progress_raw, int)
                else None
            )
            task.checklist = TaskChecklistState(
                items=items,
                completion_pct=completion_pct,
                in_progress_id=in_progress_id,
                updated_at=now,
            )
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=now,
                    kind="checklist",
                    summary=(
                        f"Checklist updated: {len(items)} item(s), "
                        f"{completion_pct}% complete"
                    ),
                )
            )

        gate_payload = updates.get("gate")
        if isinstance(gate_payload, dict):
            gate = TaskGateRecord(
                id=str(gate_payload.get("id", f"gate_{uuid.uuid4().hex[:8]}")),
                gate=str(gate_payload.get("gate", "custom")),
                command=str(gate_payload.get("command", "")),
                cwd=str(gate_payload.get("cwd", task.workspace)),
                exit_code=gate_payload.get("exit_code"),
                status=str(gate_payload.get("status", "unknown")),
                classification=str(gate_payload.get("classification", "unknown")),
                duration_ms=int(gate_payload.get("duration_ms") or 0),
                summary=str(gate_payload.get("summary", "")),
                recorded_at=str(gate_payload.get("recorded_at") or now),
                log_path=gate_payload.get("log_path"),
            )
            task.gates = [g for g in task.gates if g.id != gate.id] + [gate]
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=now,
                    kind="gate",
                    summary=_summarize_text(
                        f"Gate {gate.gate} {gate.status}: {gate.summary}",
                        TIMELINE_SUMMARY_LIMIT,
                    ),
                    detail_path=str(gate.log_path) if gate.log_path else None,
                )
            )

        artifacts_payload = updates.get("artifacts")
        if isinstance(artifacts_payload, list):
            for item in artifacts_payload:
                if not isinstance(item, dict):
                    continue
                artifact = TaskArtifactRef(
                    label=str(item.get("label", "artifact")),
                    path=str(item.get("path", "")),
                    summary=str(item.get("summary", "")),
                    created_at=str(item.get("created_at") or now),
                )
                task.artifacts.append(artifact)
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="artifact",
                        summary=f"{artifact.label}: {artifact.summary}",
                        detail_path=artifact.path,
                    )
                )

        github_payload = updates.get("github_event")
        if isinstance(github_payload, dict):
            event = TaskGithubEvent(
                id=str(github_payload.get("id", f"github_{uuid.uuid4().hex[:8]}")),
                action=str(github_payload.get("action", "")),
                target=str(github_payload.get("target", "")),
                number=int(github_payload.get("number") or 0),
                summary=str(github_payload.get("summary", "")),
                recorded_at=str(github_payload.get("recorded_at") or now),
                url=github_payload.get("url"),
            )
            task.github_events.append(event)
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=now,
                    kind="github",
                    summary=(
                        f"{event.action} {event.target}#{event.number}: "
                        f"{event.summary}"
                    ),
                )
            )

    async def record_tool_timeline(
        self,
        task_id: str,
        kind: str,
        summary: str,
        detail: str | None = None,
    ) -> None:
        """Append a live progress entry for an in-flight task and persist it.

        Called by the background executor for each tool call start/finish so the
        UI can poll ``timeline`` and show what a running task is currently doing.
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            detail_text = None
            if isinstance(detail, str) and detail.strip():
                # Keep expand payloads larger than the one-line summary but
                # still bounded for JSON task files.
                detail_text = _summarize_text(detail, 4_000)
            task.timeline.append(
                TaskTimelineEntry(
                    timestamp=_utc_now_iso(),
                    kind=kind,
                    summary=_summarize_text(summary, TIMELINE_SUMMARY_LIMIT),
                    detail=detail_text,
                )
            )
            self._persist_task_locked(task)

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
                elif task.status is TaskStatus.TIMED_OUT:
                    counts.timed_out += 1
            return counts

    def _count_running_cron_tasks_locked(self) -> int:
        return sum(
            1
            for task in self._tasks.values()
            if task.status is TaskStatus.RUNNING
            and task.prompt.lstrip().startswith(CRON_PROMPT_MARKER)
        )

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
            attempts = len(self._queue)
            while attempts > 0 and self._queue:
                attempts -= 1
                task_id = self._queue.popleft()
                task = self._tasks.get(task_id)
                if task is None or task.status is not TaskStatus.QUEUED:
                    self._persist_queue_locked()
                    continue
                if (
                    task.prompt.lstrip().startswith(CRON_PROMPT_MARKER)
                    and self._count_running_cron_tasks_locked() >= 1
                ):
                    self._queue.append(task_id)
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
                    task_manager=self,
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
            if result.timed_out:
                task.status = TaskStatus.TIMED_OUT
                task.error = result.error or "Task timed out"
                task.timeline.append(
                    TaskTimelineEntry(
                        timestamp=now,
                        kind="timed_out",
                        summary=_summarize_text(
                            task.error or "Task timed out", TIMELINE_SUMMARY_LIMIT
                        ),
                    )
                )
            elif cancel.is_set() and task.status is not TaskStatus.CANCELED:
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
            self._evict_terminal_tasks_locked()

    def _evict_terminal_tasks_locked(self) -> None:
        terminal = [
            (tid, t) for tid, t in self._tasks.items() if t.status.is_terminal()
        ]
        if len(terminal) <= _MAX_TERMINAL_IN_MEMORY:
            return
        terminal.sort(key=lambda x: x[1].ended_at or "")
        to_remove = len(terminal) - _MAX_TERMINAL_IN_MEMORY
        for tid, _ in terminal[:to_remove]:
            del self._tasks[tid]

    def _persist_all_locked(self) -> None:
        """全量落盘：先写队列，再逐个写入所有任务记录。

        调用方必须已持有 ``self._lock``（``_locked`` 约定）。用于队列
        结构性变化的场合（新增/取消/出队/收尾/启动），此时 queue 与多个
        任务状态可能同时变动，一次全写保证多文件间一致。高频的单任务
        更新应改用 :meth:`_persist_task_locked` 以避免全量写放大。
        """
        self._persist_queue_locked()
        for task in self._tasks.values():
            self._persist_task_locked(task)

    def _persist_queue_locked(self) -> None:
        """原子写入队列顺序到 ``queue.json``（调用方须持有 ``self._lock``）。"""
        _write_json_atomic(self._queue_path, {"queue": list(self._queue)})

    def _persist_task_locked(self, task: TaskRecord) -> None:
        """原子写入单个任务到 ``tasks/{id}.json``（调用方须持有 ``self._lock``）。"""
        path = self._tasks_dir / f"{task.id}.json"
        _write_json_atomic(path, _task_record_to_dict(task))
