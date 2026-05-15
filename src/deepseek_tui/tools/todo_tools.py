"""Todo / checklist tools — Python port of Rust ``crates/tui/src/tools/todo.rs``.

This module exposes a single 4-tool family — ``write`` / ``add`` /
``update`` / ``list`` — under **two** sets of names:

- ``checklist_*`` — the canonical names referenced by every system
  prompt (``base.md``, ``agent.md``, ``plan.md``, ``subagent``…).
- ``todo_*``      — legacy aliases preserved for backward compatibility
  with prior conversation transcripts and tests.

Both name sets share the same in-memory ``TodoList`` (kept on
``ToolContext.metadata['todos']``) so calls through either family read
and write the same data — mirroring Rust ``ToolRegistry::with_todo_tool``
which constructs all eight ``ToolSpec`` instances against one
``SharedTodoList``.

Each write/add/update call returns a structured snapshot under
``ToolResult.metadata['task_updates']['checklist']``. When the tool
runs inside a durable Task, an executor-installed sink forwards that
snapshot to :class:`TaskManager` which persists it to the on-disk
``TaskRecord.checklist`` (see step 3 of the audit-driven rewrite,
2026-05-11).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, cast

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

_TODO_STORE_KEY = "todos"
_TASK_ID_KEY = "task_id"
_TASK_MANAGER_KEY = "task_manager"

TodoStatus = Literal["pending", "in_progress", "completed"]

_VALID_STATUSES: tuple[TodoStatus, ...] = ("pending", "in_progress", "completed")

_STATUS_GLYPHS: dict[TodoStatus, str] = {
    "pending": "[ ]",
    "in_progress": "[~]",
    "completed": "[x]",
}


@dataclass(slots=True)
class TodoItem:
    """A single checklist item.

    Mirrors Rust ``TodoItem`` (``todo.rs:48-53``). The ``id`` stays a
    string in the Python port — legacy tests already index by str —
    while the upgraded ``status`` field replaces the prior 2-state
    ``done: bool``.
    """

    id: str
    content: str
    status: TodoStatus = "pending"

    # Legacy compatibility — older callers / tests read ``item.text`` and
    # toggle ``item.done``. These are simple computed proxies over the
    # canonical ``content`` / ``status`` fields.
    @property
    def text(self) -> str:
        return self.content

    @text.setter
    def text(self, value: str) -> None:
        self.content = value

    @property
    def done(self) -> bool:
        return self.status == "completed"

    @done.setter
    def done(self, value: bool) -> None:
        self.status = "completed" if value else "pending"


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


def _todo_store(context: ToolContext) -> dict[str, Any]:
    store = context.metadata.get(_TODO_STORE_KEY)
    if store is None:
        store = {"next_id": 1, "items": []}
        context.metadata[_TODO_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("todo store is invalid")
    items = store.get("items")
    next_id = store.get("next_id")
    if not isinstance(items, list) or not isinstance(next_id, int):
        raise ToolError("todo store is invalid")
    return store


def _require_todo(context: ToolContext, item_id: str) -> TodoItem:
    for item in _todo_store(context)["items"]:
        if isinstance(item, TodoItem) and item.id == item_id:
            return item
    raise ToolError(f"Unknown item_id: {item_id}")


def _coerce_status(value: object, *, default: TodoStatus = "pending") -> TodoStatus:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ToolError("status must be a string")
    normalised = value.strip().lower()
    if normalised in ("done",):
        return "completed"
    if normalised in ("inprogress",):
        return "in_progress"
    if normalised in _VALID_STATUSES:
        return cast(TodoStatus, normalised)
    raise ToolError(
        f"status must be one of {_VALID_STATUSES}; got {value!r}"
    )


def _enforce_single_in_progress(items: list[TodoItem]) -> None:
    """Enforce the "at most one item in_progress" invariant.

    Mirrors Rust ``TodoStore::ensure_single_in_progress`` (todo.rs:498).
    Called on every write path (add / update / write) before persisting.
    """
    in_progress_ids = [i.id for i in items if i.status == "in_progress"]
    if len(in_progress_ids) > 1:
        raise ToolError(
            f"only one item may be in_progress at a time; "
            f"already in progress: {in_progress_ids}"
        )


def _snapshot(store: dict[str, Any]) -> dict[str, Any]:
    """Serialise the store into the format Rust's ``TodoListSnapshot`` uses.

    Drives both the human-readable rendering and the ``task_updates``
    metadata side-channel.
    """
    items: list[TodoItem] = list(store["items"])
    total = len(items)
    completed = sum(1 for i in items if i.status == "completed")
    pct = round(completed * 100 / total) if total else 0
    in_progress = next(
        (int(i.id) for i in items if i.status == "in_progress" and i.id.isdigit()),
        None,
    )
    return {
        "items": [
            {"id": int(i.id) if i.id.isdigit() else i.id, "content": i.content, "status": i.status}
            for i in items
        ],
        "completion_pct": pct,
        "in_progress_id": in_progress,
        "updated_at": None,
    }


def _build_result_metadata(store: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    """Build the ``ToolResult.metadata`` payload.

    Mirrors Rust ``checklist_metadata()`` (``todo.rs:549-573``). The
    nested ``task_updates.checklist`` block is what gets routed to
    :class:`TaskManager` for durable persistence.
    """
    snap = _snapshot(store)
    return {
        "count": len(store["items"]),
        "canonical_tool": tool_name.replace("todo_", "checklist_"),
        "compat_alias": tool_name.startswith("todo_"),
        "items": [dict(it) for it in snap["items"]],
        "task_updates": {"checklist": snap},
    }


def _forward_to_task_manager(
    context: ToolContext, metadata: dict[str, Any]
) -> None:
    """Forward ``task_updates`` metadata to TaskManager when running in a Task.

    The Task executor stashes ``task_id`` + ``task_manager`` on the
    spawned Engine's ``ToolContext.metadata`` (see
    :mod:`deepseek_tui.engine.executors`). When both are present, we
    fire-and-forget a coroutine that persists the snapshot to the
    on-disk ``TaskRecord.checklist`` field, mirroring Rust's
    event-stream-driven ``apply_task_update_metadata`` path. Missing
    keys (= we're not inside a task) is the normal case and silently
    skipped.
    """
    task_id = context.metadata.get(_TASK_ID_KEY)
    manager = context.metadata.get(_TASK_MANAGER_KEY)
    if not isinstance(task_id, str) or manager is None:
        return
    if not hasattr(manager, "record_tool_metadata"):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(manager.record_tool_metadata(task_id, metadata))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class TodoWriteTool(ToolSpec):
    """Replace the active checklist.

    Registered twice in the catalog: as ``todo_write`` (legacy alias)
    and ``checklist_write`` (canonical name, matching Rust ``todo.rs``
    ``TodoWriteTool::checklist``). Both names point at the same
    in-memory store via the shared :class:`ToolContext.metadata` dict.

    Schema accepts two shapes:

    - Canonical: ``{"todos": [{"content": ..., "status": ...}, ...]}``
    - Legacy:    ``{"items": ["text1", "text2", ...]}`` — each becomes
      a pending todo.
    """

    def __init__(self, *, canonical: bool = False) -> None:
        self._canonical = canonical

    def name(self) -> str:
        return "checklist_write" if self._canonical else "todo_write"

    def description(self) -> str:
        if self._canonical:
            return (
                "Replace the active thread/task checklist. Durable tasks remain "
                "the real executable work object; this is granular progress."
            )
        return "Compatibility alias for checklist_write. Replace the active checklist."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": (
                        "Canonical: array of {content, status} objects. "
                        "Replaces the existing list."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": list(_VALID_STATUSES),
                            },
                        },
                        "required": ["content"],
                    },
                },
                "items": {
                    "type": "array",
                    "description": (
                        "Legacy: array of strings (each becomes a pending todo)."
                    ),
                    "items": {"type": "string"},
                },
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        # Prefer the canonical ``todos`` shape; fall back to legacy ``items``
        # for back-compat with old transcripts / tests.
        normalised: list[tuple[str, TodoStatus]] = []
        todos = input_data.get("todos")
        items = input_data.get("items")
        if isinstance(todos, list):
            for entry in todos:
                if isinstance(entry, str):
                    normalised.append((entry, "pending"))
                elif isinstance(entry, dict):
                    content = entry.get("content")
                    if not isinstance(content, str):
                        raise ToolError("each todo must have a string 'content'")
                    status = _coerce_status(entry.get("status"))
                    normalised.append((content, status))
                else:
                    raise ToolError("todos entries must be string or object")
        elif isinstance(items, list):
            for text in items:
                if not isinstance(text, str):
                    raise ToolError("each item must be a string")
                normalised.append((text, "pending"))
        else:
            raise ToolError("provide either 'todos' (canonical) or 'items' (legacy)")

        store = _todo_store(context)
        new_items: list[TodoItem] = []
        next_id = 1
        for content, status in normalised:
            new_items.append(TodoItem(id=str(next_id), content=content, status=status))
            next_id += 1
        _enforce_single_in_progress(new_items)
        store["items"] = new_items
        store["next_id"] = next_id

        metadata = _build_result_metadata(store, tool_name=self.name())
        _forward_to_task_manager(context, metadata)
        return ToolResult(
            success=True,
            content=f"{len(store['items'])} items written",
            metadata=metadata,
        )


class TodoAddTool(ToolSpec):
    """Append one item to the active checklist.

    Registered twice (canonical ``checklist_add`` + legacy ``todo_add``).
    """

    def __init__(self, *, canonical: bool = False) -> None:
        self._canonical = canonical

    def name(self) -> str:
        return "checklist_add" if self._canonical else "todo_add"

    def description(self) -> str:
        if self._canonical:
            return "Add one checklist item on the active thread/task."
        return "Compatibility alias for checklist_add."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "text": {
                    "type": "string",
                    "description": "Legacy alias for content.",
                },
                "status": {
                    "type": "string",
                    "enum": list(_VALID_STATUSES),
                    "description": "Optional initial status (default: pending).",
                },
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        content = _optional_string(input_data, "content")
        if content is None:
            content = _optional_string(input_data, "text")
        if content is None:
            raise ToolError("content (or legacy 'text') must be a string")
        status = _coerce_status(input_data.get("status"))
        store = _todo_store(context)
        item = TodoItem(id=str(store["next_id"]), content=content, status=status)
        candidate_items = list(store["items"]) + [item]
        _enforce_single_in_progress(candidate_items)
        store["next_id"] += 1
        store["items"].append(item)
        metadata = _build_result_metadata(store, tool_name=self.name())
        # Preserve legacy ``metadata["item"]`` shape (some tests inspect it).
        metadata["item"] = {
            "id": item.id,
            "content": item.content,
            "status": item.status,
            # Legacy mirror fields:
            "text": item.content,
            "done": item.done,
        }
        _forward_to_task_manager(context, metadata)
        return ToolResult(
            success=True,
            content=item.id,
            metadata=metadata,
        )


class TodoUpdateTool(ToolSpec):
    """Update one checklist item's content or status.

    Registered twice (canonical ``checklist_update`` + legacy ``todo_update``).
    Schema accepts both new ``status: "pending|in_progress|completed"``
    and legacy ``done: bool`` (mapped to ``completed`` / ``pending``).
    """

    def __init__(self, *, canonical: bool = False) -> None:
        self._canonical = canonical

    def name(self) -> str:
        return "checklist_update" if self._canonical else "todo_update"

    def description(self) -> str:
        if self._canonical:
            return "Update one checklist item's content or status by id."
        return "Compatibility alias for checklist_update."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "content": {"type": "string"},
                "text": {
                    "type": "string",
                    "description": "Legacy alias for content.",
                },
                "status": {
                    "type": "string",
                    "enum": list(_VALID_STATUSES),
                },
                "done": {
                    "type": "boolean",
                    "description": (
                        "Legacy: true → status=completed, false → pending. "
                        "Prefer the 'status' field."
                    ),
                },
            },
            "required": ["item_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        item = _require_todo(context, _require_string(input_data, "item_id"))
        new_content = _optional_string(input_data, "content")
        if new_content is None:
            new_content = _optional_string(input_data, "text")
        prev_content = item.content
        prev_status = item.status
        if new_content is not None:
            item.content = new_content
        if "status" in input_data:
            item.status = _coerce_status(input_data.get("status"))
        elif "done" in input_data:
            done = input_data.get("done")
            if isinstance(done, bool):
                item.status = "completed" if done else "pending"
            else:
                raise ToolError("done must be a boolean")
        store = _todo_store(context)
        try:
            _enforce_single_in_progress(list(store["items"]))
        except ToolError:
            item.content = prev_content
            item.status = prev_status
            raise
        metadata = _build_result_metadata(store, tool_name=self.name())
        metadata["item"] = {
            "id": item.id,
            "content": item.content,
            "status": item.status,
            "text": item.content,
            "done": item.done,
        }
        _forward_to_task_manager(context, metadata)
        return ToolResult(
            success=True,
            content="updated",
            metadata=metadata,
        )


class TodoListTool(ToolSpec):
    """Render the active checklist.

    Registered twice (canonical ``checklist_list`` + legacy ``todo_list``).
    """

    def __init__(self, *, canonical: bool = False) -> None:
        self._canonical = canonical

    def name(self) -> str:
        return "checklist_list" if self._canonical else "todo_list"

    def description(self) -> str:
        if self._canonical:
            return "List the active checklist with status + completion percentage."
        return "Compatibility alias for checklist_list."

    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        store = _todo_store(context)
        items: list[TodoItem] = list(store["items"])
        lines = [
            f"{_STATUS_GLYPHS.get(i.status, '[ ]')} {i.id}: {i.content}"
            for i in items
        ]
        metadata = _build_result_metadata(store, tool_name=self.name())
        # Listing is read-only — no task_updates forwarding (matches Rust:
        # ``checklist_metadata`` is only attached to write paths).
        metadata.pop("task_updates", None)
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


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


