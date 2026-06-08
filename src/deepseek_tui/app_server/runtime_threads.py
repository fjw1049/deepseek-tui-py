"""Durable thread/turn/item runtime for the HTTP API and background tasks.

Mirrors Rust ``crates/tui/src/runtime_threads.rs`` (4,413 lines).
This module keeps DeepSeek-only execution while exposing Codex-like lifecycle
semantics (threads, turns, items, interrupt/steer, and replayable events).

Split into two layers:
- Data models + RuntimeThreadStore (this file) — pure I/O, no engine logic
- RuntimeThreadManager (thread_manager.py) — orchestration + engine loading
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from deepseek_tui.utils import write_json_atomic

__all__ = [
    "CURRENT_RUNTIME_SCHEMA_VERSION",
    "EVENT_CHANNEL_CAPACITY",
    "MAX_ACTIVE_THREADS_DEFAULT",
    "RUNTIME_RESTART_REASON",
    "SUMMARY_LIMIT",
    "CompactThreadRequest",
    "CreateThreadRequest",
    "RuntimeEventRecord",
    "RuntimeStoreState",
    "RuntimeThreadManagerConfig",
    "RuntimeThreadStore",
    "RuntimeTurnStatus",
    "StartTurnRequest",
    "SteerTurnRequest",
    "ThreadDetail",
    "ThreadRecord",
    "TurnItemKind",
    "TurnItemLifecycleStatus",
    "TurnItemRecord",
    "TurnRecord",
    "UpdateThreadRequest",
]

# --- constants (mirrors Rust) ------------------------------------------------

EVENT_CHANNEL_CAPACITY: int = 1024
MAX_ACTIVE_THREADS_DEFAULT: int = 8
SUMMARY_LIMIT: int = 280
CURRENT_RUNTIME_SCHEMA_VERSION: int = 2
RUNTIME_RESTART_REASON: str = "Interrupted by process restart"


# --- enums -------------------------------------------------------------------


class RuntimeTurnStatus(str, Enum):
    """Mirrors Rust ``RuntimeTurnStatus`` (line 53)."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"


class TurnItemKind(str, Enum):
    """Mirrors Rust ``TurnItemKind`` (line 64)."""

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
    """Mirrors Rust ``TurnItemLifecycleStatus`` (line 77)."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"


# --- record models -----------------------------------------------------------


class ThreadRecord(BaseModel):
    """Mirrors Rust ``ThreadRecord`` (line 87)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_RUNTIME_SCHEMA_VERSION
    id: str
    created_at: datetime
    updated_at: datetime
    model: str
    workspace: str
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


class TurnRecord(BaseModel):
    """Mirrors Rust ``TurnRecord`` (line 114)."""

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


class TurnItemRecord(BaseModel):
    """Mirrors Rust ``TurnItemRecord`` (line 139)."""

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
    """Mirrors Rust ``RuntimeEventRecord`` (line 160)."""

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
    model: str | None = None
    workspace: str | None = None
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


class StartTurnRequest(BaseModel):
    prompt: str
    input_summary: str | None = None
    model: str | None = None
    mode: str | None = None
    allow_shell: bool | None = None
    trust_mode: bool | None = None
    auto_approve: bool | None = None
    ui_submit_at_ms: int | None = None
    main_runtime_request_start_ms: int | None = None
    hidden: bool = False
    internal_kind: str | None = None
    goal_id: str | None = None


class SteerTurnRequest(BaseModel):
    prompt: str


class CompactThreadRequest(BaseModel):
    reason: str | None = None


# --- composite response model ------------------------------------------------


class ThreadDetail(BaseModel):
    thread: ThreadRecord
    turns: list[TurnRecord] = Field(default_factory=list)
    items: list[TurnItemRecord] = Field(default_factory=list)
    latest_seq: int = 0


# --- config ------------------------------------------------------------------


class RuntimeThreadManagerConfig(BaseModel):
    """Mirrors Rust ``RuntimeThreadManagerConfig`` (line 479)."""

    data_dir: Path
    task_data_dir: Path
    max_active_threads: int = MAX_ACTIVE_THREADS_DEFAULT

    @classmethod
    def from_task_data_dir(cls, task_data_dir: Path) -> RuntimeThreadManagerConfig:
        import os

        override = os.environ.get("DEEPSEEK_RUNTIME_DIR", "").strip()
        data_dir = Path(override) if override else task_data_dir / "runtime"
        return cls(data_dir=data_dir, task_data_dir=task_data_dir)


# --- RuntimeThreadStore (file-based persistence) ----------------------------


class RuntimeThreadStore:
    """File-based store: threads/turns/items as individual JSON, events as JSONL.

    Mirrors Rust ``RuntimeThreadStore`` (line 191-476).
    """

    def __init__(self, root: Path) -> None:
        self._threads_dir = root / "threads"
        self._turns_dir = root / "turns"
        self._items_dir = root / "items"
        self._events_dir = root / "events"
        self._goals_dir = root / "goals"
        self._state_path = root / "state.json"

        for d in (
            self._threads_dir,
            self._turns_dir,
            self._items_dir,
            self._events_dir,
            self._goals_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        if self._state_path.exists():
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._state = RuntimeStoreState.model_validate(raw)
        else:
            self._state = RuntimeStoreState()
            write_json_atomic(self._state_path, self._state.model_dump())

        import asyncio

        self._seq_lock = asyncio.Lock()
        self._events_since_checkpoint = 0
        self._last_checkpoint_at = time.monotonic()

    CHECKPOINT_EVENT_INTERVAL = 16
    CHECKPOINT_MAX_INTERVAL_S = 0.5

    # --- paths ---------------------------------------------------------------

    def _thread_path(self, thread_id: str) -> Path:
        return self._threads_dir / f"{thread_id}.json"

    def _turn_path(self, turn_id: str) -> Path:
        return self._turns_dir / f"{turn_id}.json"

    def _item_path(self, item_id: str) -> Path:
        return self._items_dir / f"{item_id}.json"

    def _events_path(self, thread_id: str) -> Path:
        return self._events_dir / f"{thread_id}.jsonl"

    def goal_journal_path(self, thread_id: str) -> Path:
        return self._goals_dir / f"{thread_id}.jsonl"

    def copy_goal_journal_for_fork(self, source_thread_id: str, target_thread_id: str) -> None:
        from deepseek_tui.goal.persistence import copy_goal_journal_file

        copy_goal_journal_file(
            self.goal_journal_path(source_thread_id),
            self.goal_journal_path(target_thread_id),
        )

    # --- CRUD ----------------------------------------------------------------

    def save_thread(self, thread: ThreadRecord) -> None:
        write_json_atomic(self._thread_path(thread.id), thread.model_dump(mode="json"))

    def save_turn(self, turn: TurnRecord) -> None:
        write_json_atomic(self._turn_path(turn.id), turn.model_dump(mode="json"))

    def save_item(self, item: TurnItemRecord) -> None:
        write_json_atomic(self._item_path(item.id), item.model_dump(mode="json"))

    def load_thread(self, thread_id: str) -> ThreadRecord:
        path = self._thread_path(thread_id)
        if not path.exists():
            raise FileNotFoundError(f"Thread not found: {thread_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = ThreadRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Thread schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def load_turn(self, turn_id: str) -> TurnRecord:
        path = self._turn_path(turn_id)
        if not path.exists():
            raise FileNotFoundError(f"Turn not found: {turn_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = TurnRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Turn schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def load_item(self, item_id: str) -> TurnItemRecord:
        path = self._item_path(item_id)
        if not path.exists():
            raise FileNotFoundError(f"Item not found: {item_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = TurnItemRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Item schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def list_threads(self) -> list[ThreadRecord]:
        out: list[ThreadRecord] = []
        if not self._threads_dir.exists():
            return out
        for path in self._threads_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = ThreadRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Thread schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            out.append(record)
        out.sort(key=lambda t: t.updated_at, reverse=True)
        return out

    def list_turns_for_thread(self, thread_id: str) -> list[TurnRecord]:
        out: list[TurnRecord] = []
        if not self._turns_dir.exists():
            return out
        for path in self._turns_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = TurnRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Turn schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            if record.thread_id == thread_id:
                out.append(record)
        out.sort(key=lambda t: t.created_at)
        return out

    def list_items_for_turn(self, turn_id: str) -> list[TurnItemRecord]:
        out: list[TurnItemRecord] = []
        if not self._items_dir.exists():
            return out
        try:
            turn = self.load_turn(turn_id)
        except FileNotFoundError:
            turn = None
        if turn is not None and turn.item_ids:
            for item_id in turn.item_ids:
                try:
                    out.append(self.load_item(item_id))
                except FileNotFoundError:
                    continue
            return out
        for path in self._items_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = TurnItemRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Item schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            if record.turn_id == turn_id:
                out.append(record)
        out.sort(key=lambda i: i.started_at or datetime.min.replace(tzinfo=timezone.utc))
        return out

    # --- events (JSONL append) -----------------------------------------------

    async def append_event(
        self,
        thread_id: str,
        turn_id: str | None,
        item_id: str | None,
        event: str,
        payload: dict[str, Any],
        *,
        force_checkpoint: bool = False,
    ) -> RuntimeEventRecord:
        async with self._seq_lock:
            seq = self._state.next_seq
            self._state.next_seq += 1
            self._events_since_checkpoint += 1
            now = time.monotonic()
            checkpoint_due = force_checkpoint or (
                self._events_since_checkpoint >= self.CHECKPOINT_EVENT_INTERVAL
                or (now - self._last_checkpoint_at) >= self.CHECKPOINT_MAX_INTERVAL_S
            )
            if checkpoint_due:
                write_json_atomic(self._state_path, self._state.model_dump())
                self._events_since_checkpoint = 0
                self._last_checkpoint_at = now

        record = RuntimeEventRecord(
            schema_version=CURRENT_RUNTIME_SCHEMA_VERSION,
            seq=seq,
            timestamp=datetime.now(timezone.utc),
            thread_id=thread_id,
            turn_id=turn_id,
            item_id=item_id,
            event=event,
            payload=payload,
        )

        path = self._events_path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = record.model_dump_json()
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            if checkpoint_due:
                f.flush()

        return record

    async def flush_event_checkpoint(self) -> None:
        """Persist ``state.next_seq`` after a batched delta flush."""
        async with self._seq_lock:
            if self._events_since_checkpoint <= 0:
                return
            write_json_atomic(self._state_path, self._state.model_dump())
            self._events_since_checkpoint = 0
            self._last_checkpoint_at = time.monotonic()

    def events_since(
        self, thread_id: str, since_seq: int | None = None
    ) -> list[RuntimeEventRecord]:
        path = self._events_path(thread_id)
        if not path.exists():
            return []
        out: list[RuntimeEventRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = RuntimeEventRecord.model_validate_json(line)
            if since_seq is not None and record.seq <= since_seq:
                continue
            out.append(record)
        return out

    async def current_seq(self) -> int:
        async with self._seq_lock:
            return self._state.next_seq - 1


# --- helper functions --------------------------------------------------------


def _ordered_turn_items(
    store: RuntimeThreadStore,
    turn: TurnRecord,
) -> list[TurnItemRecord]:
    """Return turn items in persisted order (``item_ids``), with stable fallback."""
    items = store.list_items_for_turn(turn.id)
    if not items:
        return []

    kind_rank = {
        TurnItemKind.USER_MESSAGE: 0,
        TurnItemKind.AGENT_MESSAGE: 1,
    }

    def sort_key(item: TurnItemRecord) -> tuple:
        started = item.started_at or datetime.min.replace(tzinfo=timezone.utc)
        return (started, kind_rank.get(item.kind, 99), item.id)

    if not turn.item_ids:
        return sorted(items, key=sort_key)

    by_id = {item.id: item for item in items}
    ordered = [by_id[item_id] for item_id in turn.item_ids if item_id in by_id]
    seen = set(turn.item_ids)
    orphans = sorted((item for item in items if item.id not in seen), key=sort_key)
    return ordered + orphans


def reconstruct_messages_from_turns(
    store: RuntimeThreadStore,
    thread_id: str,
) -> list:
    """Rebuild Engine chat history from persisted turn items.

    Mirrors Rust ``RuntimeThreadManager::reconstruct_messages_from_turns``.
    """
    from deepseek_tui.protocol.messages import (
        Message,
        Role,
        TextBlock,
        ToolUseBlock,
    )

    messages: list[Message] = []
    for turn in store.list_turns_for_thread(thread_id):
        for item in _ordered_turn_items(store, turn):
            text = (item.detail or item.summary or "").strip()
            if item.kind == TurnItemKind.USER_MESSAGE:
                if not text:
                    continue
                messages.append(
                    Message(role=Role.USER, content=[TextBlock(text=text)])
                )
            elif item.kind == TurnItemKind.AGENT_MESSAGE:
                if not text:
                    continue
                messages.append(
                    Message(role=Role.ASSISTANT, content=[TextBlock(text=text)])
                )
            elif item.kind in {
                TurnItemKind.TOOL_CALL,
                TurnItemKind.COMMAND_EXECUTION,
                TurnItemKind.FILE_CHANGE,
            }:
                meta = item.metadata if isinstance(item.metadata, dict) else {}
                tool_use_id = str(meta.get("tool_use_id") or item.id)
                tool_name = str(meta.get("tool_name") or item.summary or "tool")
                arguments = meta.get("arguments")
                if not isinstance(arguments, dict):
                    arguments = {}
                messages.append(
                    Message.assistant_with_tools(
                        [
                            ToolUseBlock(
                                id=tool_use_id,
                                name=tool_name,
                                input=arguments,
                            )
                        ]
                    )
                )
                if item.status in {
                    TurnItemLifecycleStatus.COMPLETED,
                    TurnItemLifecycleStatus.FAILED,
                } and text:
                    messages.append(
                        Message.tool_result(
                            tool_use_id,
                            text,
                            is_error=item.status == TurnItemLifecycleStatus.FAILED,
                        )
                    )
    return messages


def tool_kind_for_name(name: str) -> TurnItemKind:
    """Mirrors Rust ``tool_kind_for_name`` (line 2542)."""
    lower = name.lower()
    if lower in ("exec_shell", "exec_shell_wait", "exec_shell_interact"):
        return TurnItemKind.COMMAND_EXECUTION
    if "patch" in lower or "write" in lower or "edit" in lower:
        return TurnItemKind.FILE_CHANGE
    return TurnItemKind.TOOL_CALL


def _parse_tool_arguments(arguments: Any) -> dict[str, Any] | None:
    args = arguments
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(args, dict):
        return None
    return args


def _is_todo_tool_name(tool_name: str) -> bool:
    lower = tool_name.lower()
    return "todo" in lower or "checklist" in lower


def _todo_items_from_arguments(args: dict[str, Any]) -> list[dict[str, Any]] | None:
    todos = args.get("todos")
    if isinstance(todos, list) and todos:
        items: list[dict[str, Any]] = []
        for index, entry in enumerate(todos, start=1):
            if isinstance(entry, str) and entry.strip():
                items.append({"id": index, "content": entry.strip(), "status": "pending"})
                continue
            if not isinstance(entry, dict):
                continue
            content = entry.get("content") or entry.get("text")
            if not isinstance(content, str) or not content.strip():
                continue
            status = entry.get("status") if isinstance(entry.get("status"), str) else "pending"
            item_id = entry.get("id", index)
            items.append(
                {
                    "id": item_id,
                    "content": content.strip(),
                    "status": status,
                }
            )
        return items or None
    legacy = args.get("items")
    if isinstance(legacy, list) and legacy:
        return [
            {"id": index, "content": str(text).strip(), "status": "pending"}
            for index, text in enumerate(legacy, start=1)
            if isinstance(text, str) and str(text).strip()
        ] or None
    return None


def todo_tool_metadata(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Expose checklist/todo payloads to Workbench sidebar consumers."""
    if not _is_todo_tool_name(tool_name):
        return None
    args = _parse_tool_arguments(arguments)
    if not args:
        return {"tool_name": tool_name}
    items = _todo_items_from_arguments(args)
    if not items:
        return {"tool_name": tool_name}
    completed = sum(
        1
        for item in items
        if str(item.get("status", "")).lower() in {"completed", "done"}
    )
    return {
        "tool_name": tool_name,
        "items": items,
        "completion_pct": round(completed * 100 / len(items)) if items else 0,
    }


def todo_tool_metadata_from_result(
    tool_name: str,
    arguments: Any,
    result_metadata: dict[str, Any] | None,
    existing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Merge checklist snapshots from tool args and result metadata for Workbench."""
    if not _is_todo_tool_name(tool_name):
        return None
    base: dict[str, Any] = dict(existing_metadata) if existing_metadata else {}
    base["tool_name"] = tool_name

    if isinstance(result_metadata, dict):
        task_updates = result_metadata.get("task_updates")
        if isinstance(task_updates, dict):
            checklist = task_updates.get("checklist")
            if isinstance(checklist, dict):
                items_raw = checklist.get("items")
                if isinstance(items_raw, list) and items_raw:
                    items: list[dict[str, Any]] = []
                    for index, entry in enumerate(items_raw, start=1):
                        if not isinstance(entry, dict):
                            continue
                        content = entry.get("content") or entry.get("text")
                        if not isinstance(content, str) or not content.strip():
                            continue
                        status = (
                            entry.get("status")
                            if isinstance(entry.get("status"), str)
                            else "pending"
                        )
                        item_id = entry.get("id", index)
                        items.append(
                            {
                                "id": item_id,
                                "content": content.strip(),
                                "status": status,
                            }
                        )
                    if items:
                        completed = sum(
                            1
                            for item in items
                            if str(item.get("status", "")).lower()
                            in {"completed", "done"}
                        )
                        base["items"] = items
                        base["completion_pct"] = (
                            round(completed * 100 / len(items)) if items else 0
                        )
                        in_progress = checklist.get("in_progress_id")
                        if in_progress is not None:
                            base["in_progress_id"] = in_progress
                        return base

    from_args = todo_tool_metadata(tool_name, arguments)
    if from_args and from_args.get("items"):
        base.update(from_args)
        return base

    args = _parse_tool_arguments(arguments)
    if args and "item_id" in args:
        items = base.get("items")
        if isinstance(items, list):
            item_id = str(args["item_id"])
            new_status: str | None = None
            if isinstance(args.get("status"), str):
                new_status = str(args["status"]).lower()
            elif isinstance(args.get("done"), bool):
                new_status = "completed" if args["done"] else "pending"
            if new_status:
                updated: list[dict[str, Any]] = []
                for row in items:
                    if not isinstance(row, dict):
                        continue
                    copy = dict(row)
                    if str(copy.get("id")) == item_id:
                        copy["status"] = new_status
                    updated.append(copy)
                base["items"] = updated
                completed = sum(
                    1
                    for item in updated
                    if str(item.get("status", "")).lower() in {"completed", "done"}
                )
                base["completion_pct"] = (
                    round(completed * 100 / len(updated)) if updated else 0
                )
                return base

    return from_args or (base if base.get("items") else None)


def tool_item_metadata(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Extract file path metadata for Workbench Diff / ChangeInspector."""
    todo_meta = todo_tool_metadata(tool_name, arguments)
    if todo_meta is not None:
        return todo_meta
    if tool_kind_for_name(tool_name) != TurnItemKind.FILE_CHANGE:
        return None
    args = _parse_tool_arguments(arguments)
    if not args:
        return None
    for key in ("path", "file_path", "filename", "target"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return {"path": value.strip()}
    return None


def _looks_like_unified_diff(text: str) -> bool:
    return any(
        line.startswith(("@@", "diff --git ", "--- ", "+++ ", "index "))
        for line in text.splitlines()
    )


def _file_path_from_arguments(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "filename", "target"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "file"


def _synthesize_edit_diff(path: str, search: str, replace: str) -> str:
    old_lines = search.splitlines() or [""]
    new_lines = replace.splitlines() or [""]
    body = [f"-{line}" for line in old_lines] + [f"+{line}" for line in new_lines]
    return f"--- a/{path}\n+++ b/{path}\n@@\n" + "\n".join(body)


def _synthesize_new_file_diff(path: str, content: str) -> str:
    lines = content.splitlines()
    count = max(len(lines), 1)
    body = "\n".join(f"+{line}" for line in lines) if lines else "+"
    return f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{count} @@\n{body}"


def file_change_completion_detail(
    tool_name: str,
    arguments: Any,
    result_content: str,
) -> str:
    """Return unified diff text for Workbench ChangeInspector when possible."""
    content = (result_content or "").strip()
    if content and _looks_like_unified_diff(content):
        return content

    args = _parse_tool_arguments(arguments)
    if not args:
        return content

    lower = tool_name.lower()
    path = _file_path_from_arguments(args)

    if lower == "apply_patch":
        patch = args.get("patch")
        if isinstance(patch, str) and _looks_like_unified_diff(patch):
            return patch
        changes = args.get("changes")
        if isinstance(changes, list) and len(changes) == 1:
            only = changes[0]
            if isinstance(only, dict):
                change_path = only.get("path")
                change_content = only.get("content")
                if isinstance(change_path, str) and isinstance(change_content, str):
                    return _synthesize_new_file_diff(change_path.strip(), change_content)

    if lower == "edit_file":
        search = args.get("search", args.get("old_string"))
        replace = args.get("replace", args.get("new_string"))
        if isinstance(search, str) and isinstance(replace, str):
            return _synthesize_edit_diff(path, search, replace)

    if lower == "write_file":
        file_content = args.get("content")
        if isinstance(file_content, str):
            return _synthesize_new_file_diff(path, file_content)

    return content


def duration_ms(start: datetime, end: datetime) -> int:
    """Milliseconds between two datetimes, clamped to >=0."""
    delta = end - start
    ms = int(delta.total_seconds() * 1000)
    return max(ms, 0)
