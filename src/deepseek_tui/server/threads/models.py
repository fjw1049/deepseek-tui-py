"""Runtime thread data models: constants, enums, records, requests, config."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --- constants ---------------------------------------------------------------

EVENT_CHANNEL_CAPACITY: int = 1024
MAX_ACTIVE_THREADS_DEFAULT: int = 8
SUMMARY_LIMIT: int = 280
CURRENT_RUNTIME_SCHEMA_VERSION: int = 2
RUNTIME_RESTART_REASON: str = "Interrupted by process restart"


# --- enums -------------------------------------------------------------------


class RuntimeTurnStatus(str, Enum):
    """Lifecycle status of a runtime turn."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"


class TurnItemKind(str, Enum):
    """Kind of item recorded within a turn."""

    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    AGENT_REASONING = "agent_reasoning"
    TOOL_CALL = "tool_call"
    FILE_CHANGE = "file_change"
    COMMAND_EXECUTION = "command_execution"
    CONTEXT_COMPACTION = "context_compaction"
    STATUS = "status"
    ERROR = "error"


class TurnItemLifecycleStatus(str, Enum):
    """Lifecycle status of a turn item."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"


# --- record models -----------------------------------------------------------


class ThreadRecord(BaseModel):
    """Persisted record for a single thread."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    id: str
    created_at: datetime
    updated_at: datetime
    model: str
    provider: str = "deepseek"
    workspace: str
    env_mode: str = "local"
    worktree_path: str | None = None
    worktree_base: str | None = None
    worktree_owned: bool = False
    associated_worktree_path: str | None = None
    worktree_branch: str | None = None
    # User-facing delivery state for isolated session edits.  Worktree and
    # checkpoint details stay internal; the UI only needs to know whether this
    # session still has code to apply, whether an apply was queued behind
    # another active session, or whether real file conflicts need a choice.
    publish_pending: bool = False
    publish_request_action: str | None = None
    publish_request_paths: list[str] = Field(default_factory=list)
    publish_waiting_on: str | None = None
    publish_blocked: bool = False
    # Structured reason for a non-file delivery problem. Keeping this out of
    # publish_conflicts lets every valid repository filename remain valid.
    publish_issue: str | None = None
    publish_conflicts: list[str] = Field(default_factory=list)
    mode: str = "agent"
    allow_shell: bool = False
    trust_mode: bool = False
    auto_approve: bool = False
    latest_turn_id: str | None = None
    latest_response_bookmark: str | None = None
    archived: bool = False
    system_prompt: str | None = None
    task_id: str | None = None
    coherence_state: str = "intro"
    title: str | None = None
    source_session_id: str | None = None
    source_session_path: str | None = None
    memory_mode: str | None = None
    approved_plan: bool = False
    goal: dict[str, Any] | None = None
    goal_queue: list[dict[str, Any]] = Field(default_factory=list)
    goal_fork_notice: bool = False


class TurnRecord(BaseModel):
    """Persisted record for a single turn."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    id: str
    thread_id: str
    status: RuntimeTurnStatus
    input_summary: str
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    steer_count: int = 0
    # Authoritative per-turn file delta. Persisted so historical receipts do
    # not fall back to lossy per-tool reconstruction after reload.
    diff_snapshot: dict[str, Any] | None = None


class TurnItemRecord(BaseModel):
    """Persisted record for a single turn item."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    id: str
    turn_id: str
    kind: TurnItemKind
    status: TurnItemLifecycleStatus
    summary: str
    detail: str | None = None
    metadata: Any | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class RuntimeEventRecord(BaseModel):
    """Persisted record for a single runtime event."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    seq: int
    timestamp: datetime
    thread_id: str
    turn_id: str | None = None
    item_id: str | None = None
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeStoreState(BaseModel):
    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    next_seq: int = 1


# --- request models ----------------------------------------------------------


class CreateThreadRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    workspace: str | None = None
    title: str | None = None
    env_mode: str | None = None
    mode: str | None = None
    allow_shell: bool | None = None
    trust_mode: bool | None = None
    auto_approve: bool | None = None
    archived: bool = False
    system_prompt: str | None = None
    task_id: str | None = None


class UpdateThreadRequest(BaseModel):
    archived: bool | None = None
    title: str | None = None
    memory_mode: str | None = None


class ForkThreadRequest(BaseModel):
    """Optional cutoff for fork-from-a-point.

    When ``through_item_id`` is omitted the whole thread is forked (legacy
    behavior). When provided, the forked thread contains the conversation up
    to and including that turn item.
    """

    through_item_id: str | None = None


class RewindThreadRequest(BaseModel):
    """Truncate a thread in place, dropping ``before_item_id`` and after."""

    before_item_id: str
    # Also roll the dropped turns' workspace files back to their pre-turn
    # state (per-turn file checkpoints). Conversation is truncated either way.
    restore_files: bool = False
    # Overwrite paths whose current content diverged from what the turns
    # left behind (third-party edits) instead of leaving them untouched.
    force_conflicts: bool = False


class RestoreCodeRequest(BaseModel):
    """Roll workspace files back to ``before_item_id``, conversation intact."""

    before_item_id: str
    # Same semantics as RewindThreadRequest.force_conflicts.
    force_conflicts: bool = False


class ResolvePublishRequest(BaseModel):
    """Apply isolated edits or resolve files that could not be merged."""

    # ``apply`` performs the normal safe merge requested by the user.
    # ``use_agent`` overwrites the project with this thread's copies.
    # ``keep_project`` keeps the project bytes and drops those isolate edits.
    action: str
    paths: list[str] | None = None
    # Snapshot token shown with a recovery choice. The manager rejects stale
    # destructive choices instead of applying a newer unseen recovery state.
    recovery_token: str | None = None


class StartTurnRequest(BaseModel):
    prompt: str
    input_summary: str | None = None
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    mode: str | None = None
    allow_shell: bool | None = None
    trust_mode: bool | None = None
    auto_approve: bool | None = None
    ui_submit_at_ms: int | None = None
    main_runtime_request_start_ms: int | None = None
    hidden: bool = False
    internal_kind: str | None = None


class SteerTurnRequest(BaseModel):
    prompt: str


class CompactThreadRequest(BaseModel):
    reason: str | None = None


class GoalCommandRequest(BaseModel):
    args: str = ""
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


# --- composite response model ------------------------------------------------


class ThreadDetail(BaseModel):
    thread: ThreadRecord
    turns: list[TurnRecord] = Field(default_factory=list)
    items: list[TurnItemRecord] = Field(default_factory=list)
    latest_seq: int = 0


# --- config ------------------------------------------------------------------


class RuntimeThreadManagerConfig(BaseModel):
    """Configuration for the runtime thread manager."""

    data_dir: Path
    task_data_dir: Path
    max_active_threads: int = MAX_ACTIVE_THREADS_DEFAULT

    @classmethod
    def from_task_data_dir(cls, task_data_dir: Path) -> RuntimeThreadManagerConfig:
        import os

        override = os.environ.get("DEEPSEEK_RUNTIME_DIR", "").strip()
        data_dir = Path(override) if override else task_data_dir / "runtime"
        return cls(data_dir=data_dir, task_data_dir=task_data_dir)
