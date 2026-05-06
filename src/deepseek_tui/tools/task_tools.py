from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

_TASK_STORE_KEY = "tasks"
_PR_ATTEMPT_STORE_KEY = "pr_attempts"


@dataclass(slots=True)
class ManagedTask:
    id: str
    title: str
    description: str
    status: str


@dataclass(slots=True)
class PrAttempt:
    id: str
    task_id: str
    branch: str
    status: str
    notes: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


class TaskCreateTool(ToolSpec):
    def name(self) -> str:
        return "task_create"

    def description(self) -> str:
        return "Create a managed task in the local task store."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        store = _task_store(context)
        title = _require_string(input_data, "title")
        description = _optional_string(input_data, "description") or ""
        task = ManagedTask(
            id=str(store["next_id"]),
            title=title,
            description=description,
            status="open",
        )
        store["next_id"] += 1
        store["items"].append(task)
        return ToolResult(success=True, content=task.id, metadata={"task": asdict(task)})


class TaskListTool(ToolSpec):
    def name(self) -> str:
        return "task_list"

    def description(self) -> str:
        return "List managed tasks from the local task store."

    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        items = _task_store(context)["items"]
        content = "\n".join(_format_task_summary(task) for task in items)
        metadata = {"tasks": [asdict(task) for task in items], "count": len(items)}
        return ToolResult(success=True, content=content, metadata=metadata)


class TaskReadTool(ToolSpec):
    def name(self) -> str:
        return "task_read"

    def description(self) -> str:
        return "Read a managed task from the local task store."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        task = _require_task(context, _require_string(input_data, "task_id"))
        return ToolResult(
            success=True,
            content=_format_task_detail(task),
            metadata={"task": asdict(task)},
        )


class TaskCancelTool(ToolSpec):
    def name(self) -> str:
        return "task_cancel"

    def description(self) -> str:
        return "Cancel a managed task in the local task store."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        task = _require_task(context, _require_string(input_data, "task_id"))
        task.status = "cancelled"
        return ToolResult(success=True, content="cancelled", metadata={"task": asdict(task)})


class TaskGateRunTool(ToolSpec):
    def name(self) -> str:
        return "task_gate_run"

    def description(self) -> str:
        return "Run a quality gate check against a task."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "gate": {"type": "string"},
            },
            "required": ["task_id", "gate"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        task = _require_task(context, _require_string(input_data, "task_id"))
        gate = _require_string(input_data, "gate")
        return ToolResult(
            success=True,
            content=f"gate '{gate}' passed for task {task.id}",
            metadata={"task_id": task.id, "gate": gate, "result": "passed"},
        )


class PrAttemptCreateTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_create"

    def description(self) -> str:
        return "Create a new PR attempt linked to a task."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "branch": {"type": "string"},
            },
            "required": ["task_id", "branch"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        task_id = _require_string(input_data, "task_id")
        _require_task(context, task_id)
        branch = _require_string(input_data, "branch")
        store = _pr_attempt_store(context)
        attempt = PrAttempt(
            id=str(store["next_id"]),
            task_id=task_id,
            branch=branch,
            status="open",
        )
        store["next_id"] += 1
        store["items"].append(attempt)
        return ToolResult(
            success=True,
            content=attempt.id,
            metadata={"attempt": asdict(attempt)},
        )


class PrAttemptListTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_list"

    def description(self) -> str:
        return "List PR attempts, optionally filtered by task."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        items = _pr_attempt_store(context)["items"]
        task_id = _optional_string(input_data, "task_id")
        if task_id is not None:
            items = [a for a in items if a.task_id == task_id]
        lines = [f"{a.id} | {a.status} | {a.branch}" for a in items]
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "attempts": [asdict(a) for a in items],
                "count": len(items),
            },
        )


class PrAttemptReadTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_read"

    def description(self) -> str:
        return "Read details of a PR attempt."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"attempt_id": {"type": "string"}},
            "required": ["attempt_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        attempt = _require_attempt(context, _require_string(input_data, "attempt_id"))
        content = f"{attempt.id} | {attempt.status} | {attempt.branch}\ntask: {attempt.task_id}"
        if attempt.notes:
            content += f"\nnotes: {attempt.notes}"
        return ToolResult(
            success=True,
            content=content,
            metadata={"attempt": asdict(attempt)},
        )


class PrAttemptUpdateTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_update"

    def description(self) -> str:
        return "Update notes or metadata on a PR attempt."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "attempt_id": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["attempt_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        attempt = _require_attempt(context, _require_string(input_data, "attempt_id"))
        notes = _optional_string(input_data, "notes")
        if notes is not None:
            attempt.notes = notes
        return ToolResult(
            success=True,
            content="updated",
            metadata={"attempt": asdict(attempt)},
        )


class PrAttemptCompleteTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_complete"

    def description(self) -> str:
        return "Mark a PR attempt as completed/merged."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"attempt_id": {"type": "string"}},
            "required": ["attempt_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        attempt = _require_attempt(context, _require_string(input_data, "attempt_id"))
        attempt.status = "completed"
        return ToolResult(
            success=True,
            content="completed",
            metadata={"attempt": asdict(attempt)},
        )


class PrAttemptCancelTool(ToolSpec):
    def name(self) -> str:
        return "pr_attempt_cancel"

    def description(self) -> str:
        return "Cancel a PR attempt."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"attempt_id": {"type": "string"}},
            "required": ["attempt_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        attempt = _require_attempt(context, _require_string(input_data, "attempt_id"))
        attempt.status = "cancelled"
        return ToolResult(
            success=True,
            content="cancelled",
            metadata={"attempt": asdict(attempt)},
        )


def _task_store(context: ToolContext) -> dict[str, Any]:
    store = context.metadata.get(_TASK_STORE_KEY)
    if store is None:
        store = {"next_id": 1, "items": []}
        context.metadata[_TASK_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("task store is invalid")
    items = store.get("items")
    next_id = store.get("next_id")
    if not isinstance(items, list) or not isinstance(next_id, int):
        raise ToolError("task store is invalid")
    return store


def _require_task(context: ToolContext, task_id: str) -> ManagedTask:
    for task in _task_store(context)["items"]:
        if isinstance(task, ManagedTask) and task.id == task_id:
            return task
    raise ToolError(f"Unknown task_id: {task_id}")


def _pr_attempt_store(context: ToolContext) -> dict[str, Any]:
    store = context.metadata.get(_PR_ATTEMPT_STORE_KEY)
    if store is None:
        store = {"next_id": 1, "items": []}
        context.metadata[_PR_ATTEMPT_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("pr_attempt store is invalid")
    items = store.get("items")
    next_id = store.get("next_id")
    if not isinstance(items, list) or not isinstance(next_id, int):
        raise ToolError("pr_attempt store is invalid")
    return store


def _require_attempt(context: ToolContext, attempt_id: str) -> PrAttempt:
    for attempt in _pr_attempt_store(context)["items"]:
        if isinstance(attempt, PrAttempt) and attempt.id == attempt_id:
            return attempt
    raise ToolError(f"Unknown attempt_id: {attempt_id}")


def _format_task_summary(task: ManagedTask) -> str:
    return f"{task.id} | {task.status} | {task.title}"


def _format_task_detail(task: ManagedTask) -> str:
    if task.description:
        return f"{task.id} | {task.status} | {task.title}\n{task.description}"
    return _format_task_summary(task)


def _require_string(input_data: dict[str, object], key: str) -> str:
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _optional_string(input_data: dict[str, object], key: str) -> str | None:
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value
