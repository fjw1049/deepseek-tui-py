"""
Durable task data models and constants.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


def _summarize_text(text: str, limit: int) -> str:
    from deepseek_tui.utils import summarize_text

    return summarize_text(text, limit)


# Durable task manager.
#
# Persists each task as its own JSON file under ``./.deepseek/tasks/`` and
# maintains a queue in ``queue.json`` so tasks survive process restarts.
#

CURRENT_TASK_SCHEMA_VERSION = 2
TIMELINE_SUMMARY_LIMIT = 240
ARTIFACT_THRESHOLD = 1200
MAX_WORKERS = 4
_MAX_TERMINAL_IN_MEMORY = 50
# Running tasks older than this at recovery are failed instead of re-queued.
STALE_RUNNING_TASK_SECONDS = 300
CRON_PROMPT_MARKER = "[cron:"
STALE_RESTART_ERROR = "Task interrupted (stale after restart)"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    TIMED_OUT = "timed_out"

    def is_terminal(self) -> bool:
        return self in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELED,
            TaskStatus.TIMED_OUT,
        )

    def is_resumable(self) -> bool:
        """Terminal states that may re-queue for transcript resume."""
        return self in (
            TaskStatus.CANCELED,
            TaskStatus.TIMED_OUT,
            TaskStatus.FAILED,
        )


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
    # Optional longer body for Workbench step-flow expand (tool output, etc.).
    detail: str | None = None


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
    timed_out: int = 0


@dataclass(slots=True)
class NewTaskRequest:
    prompt: str
    model: str | None = None
    workspace: str | None = None
    mode: str | None = None
    allow_shell: bool | None = None
    trust_mode: bool | None = None
    auto_approve: bool | None = None
    thread_id: str | None = None


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
    # Back-reference to the owning TaskManager, populated by
    # ``TaskManager._pop_next_task``. Executors propagate it to the
    # spawned Engine's ``ToolContext.metadata`` so tools like
    # ``checklist_write`` can forward their snapshots to the durable
    # task record via :meth:`TaskManager.record_tool_metadata`.
    # Typed as ``Any`` to avoid a forward reference / circular type.
    task_manager: Any = None


@dataclass(slots=True)
class TaskExecutionResult:
    summary: str
    detail: str | None = None
    error: str | None = None
    timed_out: bool = False


ExecutorFunc = Callable[[ExecutionTask, asyncio.Event], Awaitable[TaskExecutionResult]]


def default_tasks_dir() -> Path:
    """``~/.deepseek/tasks/`` — cross-project task queue.

    User-level so
    background tasks survive across project switches. ``DEEPSEEK_TASKS_DIR``
    env var overrides.
    """
    from deepseek_tui.config.paths import user_tasks_dir

    return user_tasks_dir()
