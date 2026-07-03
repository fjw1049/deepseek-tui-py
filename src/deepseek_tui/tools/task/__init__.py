"""Task lifecycle — tools and durable persistence manager.

Split by responsibility:

- :mod:`.models`      — task records, requests, constants
- :mod:`.store`       — (de)serialization + on-disk state loading
- :mod:`.manager`     — durable TaskManager (queue + workers)
- :mod:`.helpers`     — shared tool helpers (input parsing, git probes)
- :mod:`.tools`       — task CRUD/gate/shell tools
- :mod:`.pr_attempts` — PR-attempt tools

``deepseek_tui.tools.task`` keeps re-exporting the public names.
"""

from deepseek_tui.tools.task.manager import (  # noqa: F401 — _stub_executor used by tests
    TaskManager,
    _stub_executor,
    get_real_task_executor,
)
from deepseek_tui.tools.task.models import (
    ARTIFACT_THRESHOLD,
    CRON_PROMPT_MARKER,
    CURRENT_TASK_SCHEMA_VERSION,
    MAX_WORKERS,
    STALE_RESTART_ERROR,
    STALE_RUNNING_TASK_SECONDS,
    TIMELINE_SUMMARY_LIMIT,
    ExecutionTask,
    ExecutorFunc,
    NewTaskRequest,
    TaskArtifactRef,
    TaskAttemptRecord,
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
    TaskToolCallSummary,
    TaskToolStatus,
    default_tasks_dir,
)
from deepseek_tui.tools.task.pr_attempts import (
    PrAttemptListTool,
    PrAttemptPreflightTool,
    PrAttemptReadTool,
    PrAttemptRecordTool,
)
from deepseek_tui.tools.task.store import (  # noqa: F401 — _is_stale_running_task used by tests
    _is_stale_running_task,
)
from deepseek_tui.tools.task.tools import (
    TaskCancelTool,
    TaskCreateTool,
    TaskGateRunTool,
    TaskListTool,
    TaskReadTool,
    TaskShellStartTool,
    TaskShellWaitTool,
)

__all__ = [
    "ARTIFACT_THRESHOLD",
    "CRON_PROMPT_MARKER",
    "CURRENT_TASK_SCHEMA_VERSION",
    "MAX_WORKERS",
    "STALE_RESTART_ERROR",
    "STALE_RUNNING_TASK_SECONDS",
    "TIMELINE_SUMMARY_LIMIT",
    "ExecutionTask",
    "ExecutorFunc",
    "NewTaskRequest",
    "PrAttemptListTool",
    "PrAttemptPreflightTool",
    "PrAttemptReadTool",
    "PrAttemptRecordTool",
    "TaskArtifactRef",
    "TaskAttemptRecord",
    "TaskCancelTool",
    "TaskChecklistItem",
    "TaskChecklistState",
    "TaskCounts",
    "TaskCreateTool",
    "TaskExecutionResult",
    "TaskGateRecord",
    "TaskGateRunTool",
    "TaskGithubEvent",
    "TaskListTool",
    "TaskManager",
    "TaskManagerConfig",
    "TaskReadTool",
    "TaskRecord",
    "TaskShellStartTool",
    "TaskShellWaitTool",
    "TaskStatus",
    "TaskSummary",
    "TaskTimelineEntry",
    "TaskToolCallSummary",
    "TaskToolStatus",
    "default_tasks_dir",
    "get_real_task_executor",
]
