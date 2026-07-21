"""Durable thread/turn/item runtime for the HTTP API and background tasks.

Split into layers:

- :mod:`.broadcast` — multi-consumer SSE broadcast channel
- :mod:`.models`    — constants, enums, record/request pydantic models
- :mod:`.usage`     — token/cost usage aggregation
- :mod:`.store`     — file-based persistence (JSON + JSONL)
- :mod:`.items`     — turn-item presentation helpers
- :mod:`.manager`   — RuntimeThreadManager engine orchestration

All public names re-exported here so ``deepseek_tui.server.threads``
keeps working as an import path.
"""

from deepseek_tui.server.threads.broadcast import AsyncBroadcast
from deepseek_tui.server.threads.items import (
    file_change_completion_detail,
    reconstruct_messages_from_turn,
    reconstruct_messages_from_turns,
    task_tool_metadata_from_result,
    todo_tool_metadata,
    todo_tool_metadata_from_result,
    tool_item_metadata,
    tool_kind_for_name,
    tool_started_metadata,
    duration_ms,
)
from deepseek_tui.server.threads.manager import (  # noqa: F401 — underscore names kept for tests
    RuntimeThreadManager,
    _ActiveThreadState,
    _ActiveTurnState,
    _PendingUserInputRecord,
)
from deepseek_tui.server.threads.models import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    EVENT_CHANNEL_CAPACITY,
    MAX_ACTIVE_THREADS_DEFAULT,
    RUNTIME_RESTART_REASON,
    SUMMARY_LIMIT,
    CompactThreadRequest,
    CreateThreadRequest,
    ForkThreadRequest,
    RewindThreadRequest,
    RuntimeEventRecord,
    RuntimeStoreState,
    RuntimeThreadManagerConfig,
    RuntimeTurnStatus,
    StartTurnRequest,
    SteerTurnRequest,
    ThreadDetail,
    ThreadRecord,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    UpdateThreadRequest,
)
from deepseek_tui.server.threads.store import RuntimeThreadStore
from deepseek_tui.server.threads.usage import (
    accumulate_model_usage_from_turn,
    aggregate_thread_usage_bucket,
    build_turn_usage_record,
    session_model_usage_response,
    thread_usage_bucket_has_data,
    thread_usage_response,
    turn_usage_from_engine_or_event,
)

__all__ = [
    "CURRENT_RUNTIME_SCHEMA_VERSION",
    "EVENT_CHANNEL_CAPACITY",
    "MAX_ACTIVE_THREADS_DEFAULT",
    "RUNTIME_RESTART_REASON",
    "SUMMARY_LIMIT",
    "AsyncBroadcast",
    "CompactThreadRequest",
    "CreateThreadRequest",
    "ForkThreadRequest",
    "RewindThreadRequest",
    "RuntimeEventRecord",
    "RuntimeStoreState",
    "RuntimeThreadManager",
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
    "accumulate_model_usage_from_turn",
    "aggregate_thread_usage_bucket",
    "build_turn_usage_record",
    "duration_ms",
    "file_change_completion_detail",
    "reconstruct_messages_from_turn",
    "reconstruct_messages_from_turns",
    "session_model_usage_response",
    "task_tool_metadata_from_result",
    "thread_usage_bucket_has_data",
    "thread_usage_response",
    "todo_tool_metadata",
    "todo_tool_metadata_from_result",
    "tool_item_metadata",
    "tool_kind_for_name",
    "tool_started_metadata",
    "turn_usage_from_engine_or_event",
]
