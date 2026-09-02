"""Task lifecycle — tools and durable persistence manager.

Split by responsibility:

- :mod:`.models`  — task records, requests, constants
- :mod:`.store`   — (de)serialization + on-disk state loading
- :mod:`.manager` — durable TaskManager (queue + workers)
- :mod:`.helpers` — shared tool helpers (input parsing, results)
- :mod:`.tools`   — task create/list/output/stop tools

``deepseek_tui.tools.task`` keeps re-exporting the public names.
"""

from deepseek_tui.tools.task.manager import (  # noqa: F401 — _stub_executor used by tests
    TaskManager,
    _stub_executor,
    get_real_task_executor,
)
from deepseek_tui.tools.task.models import (
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
    TaskChecklistItem,
    TaskChecklistState,
    TaskCounts,
    TaskExecutionResult,
    TaskManagerConfig,
    TaskRecord,
    TaskStatus,
    TaskSummary,
    TaskTimelineEntry,
    default_tasks_dir,
)
from deepseek_tui.tools.task.store import (  # noqa: F401 — _is_stale_running_task used by tests
    _is_stale_running_task,
)
from deepseek_tui.tools.task.tools import (
    TaskCreateTool,
    TaskListTool,
    TaskOutputTool,
    TaskStopTool,
)

__all__ = [
    "CRON_PROMPT_MARKER",
    "CURRENT_TASK_SCHEMA_VERSION",
    "MAX_WORKERS",
    "STALE_RESTART_ERROR",
    "STALE_RUNNING_TASK_SECONDS",
    "TIMELINE_SUMMARY_LIMIT",
    "ExecutionTask",
    "ExecutorFunc",
    "NewTaskRequest",
    "TaskArtifactRef",
    "TaskChecklistItem",
    "TaskChecklistState",
    "TaskCounts",
    "TaskCreateTool",
    "TaskExecutionResult",
    "TaskListTool",
    "TaskManager",
    "TaskManagerConfig",
    "TaskOutputTool",
    "TaskRecord",
    "TaskStatus",
    "TaskStopTool",
    "TaskSummary",
    "TaskTimelineEntry",
    "default_tasks_dir",
    "get_real_task_executor",
]
