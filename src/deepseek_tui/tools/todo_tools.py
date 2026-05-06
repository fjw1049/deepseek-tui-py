from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

_TODO_STORE_KEY = "todos"


@dataclass(slots=True)
class TodoItem:
    id: str
    text: str
    done: bool


class TodoWriteTool(ToolSpec):
    def name(self) -> str:
        return "todo_write"

    def description(self) -> str:
        return "Replace the entire todo list with a new set of items."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["items"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        raw_items = input_data.get("items")
        if not isinstance(raw_items, list):
            raise ToolError("items must be an array")
        store = _todo_store(context)
        store["items"] = []
        store["next_id"] = 1
        for text in raw_items:
            if not isinstance(text, str):
                raise ToolError("each item must be a string")
            item = TodoItem(id=str(store["next_id"]), text=text, done=False)
            store["next_id"] += 1
            store["items"].append(item)
        return ToolResult(
            success=True,
            content=f"{len(store['items'])} items written",
            metadata={"count": len(store["items"])},
        )


class TodoAddTool(ToolSpec):
    def name(self) -> str:
        return "todo_add"

    def description(self) -> str:
        return "Add a single item to the todo list."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        text = _require_string(input_data, "text")
        store = _todo_store(context)
        item = TodoItem(id=str(store["next_id"]), text=text, done=False)
        store["next_id"] += 1
        store["items"].append(item)
        return ToolResult(
            success=True,
            content=item.id,
            metadata={"item": asdict(item)},
        )


class TodoUpdateTool(ToolSpec):
    def name(self) -> str:
        return "todo_update"

    def description(self) -> str:
        return "Update a todo item's text or done status."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "text": {"type": "string"},
                "done": {"type": "boolean"},
            },
            "required": ["item_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        item = _require_todo(context, _require_string(input_data, "item_id"))
        text = _optional_string(input_data, "text")
        if text is not None:
            item.text = text
        done = input_data.get("done")
        if isinstance(done, bool):
            item.done = done
        return ToolResult(
            success=True,
            content="updated",
            metadata={"item": asdict(item)},
        )


class TodoListTool(ToolSpec):
    def name(self) -> str:
        return "todo_list"

    def description(self) -> str:
        return "List all todo items."

    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        items = _todo_store(context)["items"]
        lines = [f"{'[x]' if i.done else '[ ]'} {i.id}: {i.text}" for i in items]
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "items": [asdict(i) for i in items],
                "count": len(items),
            },
        )


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
