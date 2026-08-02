"""Todo / checklist tool.

This module exposes a single ``checklist`` tool operating on
one in-memory ``TodoList`` (kept on ``ToolContext.metadata['todos']``).
Providing ``todos`` replaces the whole checklist; omitting ``todos``
returns the current checklist (read-only).

History note: this tool was previously a 2-tool family
(``checklist_write`` / ``checklist_list``), and before that was also
registered under legacy ``todo_*`` aliases. Duplicate entries in the
model's catalog made models flail between identical tools, so the
family was merged into one tool. Historical transcripts that recorded
``checklist_*`` / ``todo_*`` calls still render fine — the renderer
matches those name families by regex and does not require the tool to
still exist.

Each write call returns a structured snapshot under
``ToolResult.metadata['task_updates']['checklist']``. When the tool
runs inside a durable Task, an executor-installed sink forwards that
snapshot to :class:`TaskManager` which persists it to the on-disk
``TaskRecord.checklist`` (see step 3 of the audit-driven rewrite,
2026-05-11).
"""

from __future__ import annotations


import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal, cast

_LOG = logging.getLogger(__name__)

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext

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

    The ``id`` stays a
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


def _render_items(items: list[TodoItem]) -> str:
    return "\n".join(
        f"{_STATUS_GLYPHS.get(i.status, '[ ]')} {i.id}: {i.content}" for i in items
    )


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

    Called on every write path (``checklist`` with ``todos``) before
    persisting.
    """
    in_progress_ids = [i.id for i in items if i.status == "in_progress"]
    if len(in_progress_ids) > 1:
        raise ToolError(
            f"only one item may be in_progress at a time "
            f"(already in progress: {in_progress_ids}). "
            f"For parallel sub-agents, keep one coordinator item in_progress "
            f"and track per-agent state via the Agents panel."
        )


def _snapshot(store: dict[str, Any]) -> dict[str, Any]:
    """Serialise the store into the ``TodoListSnapshot`` on-disk format.

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

    The nested ``task_updates.checklist`` block is what gets routed to
    :class:`TaskManager` for durable persistence.
    """
    snap = _snapshot(store)
    return {
        "count": len(store["items"]),
        "canonical_tool": tool_name,
        "items": [dict(it) for it in snap["items"]],
        "task_updates": {"checklist": snap},
    }


def _forward_to_task_manager(
    context: ToolContext, metadata: dict[str, Any]
) -> None:
    """Forward ``task_updates`` metadata to TaskManager when running in a Task.

    The Task executor stashes ``task_id`` + ``task_manager`` on the
    spawned Engine's ``ToolContext.metadata`` (see
    :mod:`deepseek_tui.engine.dispatch`). When both are present, we
    fire-and-forget a coroutine that persists the snapshot to the
    on-disk ``TaskRecord.checklist`` field. Missing keys (= we're not
    inside a task) is the normal case and silently skipped.
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


class ChecklistTool(ToolSpec):
    """Read or replace the active checklist.

    Operates on the shared in-memory store via :class:`ToolContext.metadata`.

    - ``todos`` provided → full-list rewrite (replaces the entire checklist).
    - ``todos`` omitted → returns the current checklist (read-only).

    Schema accepts the canonical shape
    ``{"todos": [{"content": ..., "status": ...}, ...]}``. The legacy
    ``items`` argument (array of strings, each becoming a pending todo) is
    still accepted at the execution layer as an alias for ``todos`` but is
    intentionally absent from the schema.
    """

    def name(self) -> str:
        return "checklist"

    def description(self) -> str:
        return (
            "The canonical progress tracker for multi-step work — use it "
            "whenever a task has more than a couple of steps and keep it "
            "current as you go. Provide `todos` to replace the entire "
            "checklist (full-list rewrite; at most one item may be "
            "in_progress at a time). Omit `todos` to read the current "
            "checklist with status + completion percentage. Durable tasks "
            "remain the real executable work object; this is granular "
            "progress."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": (
                        "Array of {content, status} objects. When provided, "
                        "replaces the existing list; when omitted, the tool "
                        "returns the current checklist unchanged."
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
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    def approval_requirement_for_input(
        self, input_data: dict[str, Any]
    ) -> ApprovalRequirement:
        # Omitting ``todos`` (and the legacy ``items`` alias) is a pure read —
        # keep it prompt-free like the pre-merge checklist_list.
        if isinstance(input_data, dict):
            if input_data.get("todos") is not None or input_data.get("items") is not None:
                return ApprovalRequirement.SUGGEST
            return ApprovalRequirement.AUTO
        return ApprovalRequirement.SUGGEST

    def is_read_only_for_input(self, input_data: dict[str, Any]) -> bool:
        # Static capabilities are WRITES_FILES, which would serialize pure
        # reads; a call without todos/items only reads the current list.
        if isinstance(input_data, dict):
            return input_data.get("todos") is None and input_data.get("items") is None
        return False

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        todos = input_data.get("todos")
        if todos is None:
            items = input_data.get("items")
            if items is not None:
                _LOG.debug(
                    "checklist: legacy 'items' alias used; mapping to 'todos'"
                )
                todos = items
        if todos is None:
            return self._read(context)
        return self._write(todos, context)

    def _write(self, todos: object, context: ToolContext) -> ToolResult:
        if not isinstance(todos, list):
            raise ToolError("'todos' must be an array")
        normalised: list[tuple[str, TodoStatus]] = []
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
        # Echo the whole list back, not just a count: the model's only other
        # view of the checklist is its own earlier tool_call arguments, which
        # L0 prune blanks at 50% and rewrite compaction drops at 75%. The
        # leading "N items written" is load-bearing — the Workbench renderer
        # matches it to detect writes (extract-todos-from-blocks.ts).
        header = f"{len(store['items'])} items written"
        body = _render_items(new_items)
        return ToolResult(
            success=True,
            content=f"{header}\n{body}" if body else header,
            metadata=metadata,
        )

    def _read(self, context: ToolContext) -> ToolResult:
        store = _todo_store(context)
        items: list[TodoItem] = list(store["items"])
        metadata = _build_result_metadata(store, tool_name=self.name())
        # Reading is read-only — no task_updates forwarding
        # (``checklist_metadata`` is only attached to write paths).
        metadata.pop("task_updates", None)
        return ToolResult(
            success=True,
            content=_render_items(items),
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------




