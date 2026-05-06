from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

_AUTOMATION_STORE_KEY = "automations"


@dataclass(slots=True)
class Automation:
    id: str
    name: str
    trigger: str
    action: str
    status: str
    metadata: dict[str, object] = field(default_factory=dict)


class AutomationCreateTool(ToolSpec):
    def name(self) -> str:
        return "automation_create"

    def description(self) -> str:
        return "Create a new automation rule."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "trigger": {"type": "string"},
                "action": {"type": "string"},
            },
            "required": ["name", "trigger", "action"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        store = _automation_store(context)
        auto = Automation(
            id=str(store["next_id"]),
            name=_require_string(input_data, "name"),
            trigger=_require_string(input_data, "trigger"),
            action=_require_string(input_data, "action"),
            status="active",
        )
        store["next_id"] += 1
        store["items"].append(auto)
        return ToolResult(
            success=True,
            content=auto.id,
            metadata={"automation": asdict(auto)},
        )


class AutomationListTool(ToolSpec):
    def name(self) -> str:
        return "automation_list"

    def description(self) -> str:
        return "List all automation rules."

    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        items = _automation_store(context)["items"]
        lines = [f"{a.id} | {a.status} | {a.name}" for a in items]
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "automations": [asdict(a) for a in items],
                "count": len(items),
            },
        )


class AutomationReadTool(ToolSpec):
    def name(self) -> str:
        return "automation_read"

    def description(self) -> str:
        return "Read details of an automation rule."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        auto = _require_automation(context, _require_string(input_data, "automation_id"))
        content = (
            f"{auto.id} | {auto.status} | {auto.name}\n"
            f"trigger: {auto.trigger}\naction: {auto.action}"
        )
        return ToolResult(
            success=True,
            content=content,
            metadata={"automation": asdict(auto)},
        )


class AutomationUpdateTool(ToolSpec):
    def name(self) -> str:
        return "automation_update"

    def description(self) -> str:
        return "Update an automation rule's trigger or action."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "automation_id": {"type": "string"},
                "trigger": {"type": "string"},
                "action": {"type": "string"},
            },
            "required": ["automation_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        auto = _require_automation(context, _require_string(input_data, "automation_id"))
        trigger = _optional_string(input_data, "trigger")
        action = _optional_string(input_data, "action")
        if trigger is not None:
            auto.trigger = trigger
        if action is not None:
            auto.action = action
        return ToolResult(
            success=True,
            content="updated",
            metadata={"automation": asdict(auto)},
        )


class AutomationPauseTool(ToolSpec):
    def name(self) -> str:
        return "automation_pause"

    def description(self) -> str:
        return "Pause an active automation rule."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        auto = _require_automation(context, _require_string(input_data, "automation_id"))
        auto.status = "paused"
        return ToolResult(
            success=True,
            content="paused",
            metadata={"automation": asdict(auto)},
        )


class AutomationResumeTool(ToolSpec):
    def name(self) -> str:
        return "automation_resume"

    def description(self) -> str:
        return "Resume a paused automation rule."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        auto = _require_automation(context, _require_string(input_data, "automation_id"))
        auto.status = "active"
        return ToolResult(
            success=True,
            content="resumed",
            metadata={"automation": asdict(auto)},
        )


class AutomationDeleteTool(ToolSpec):
    def name(self) -> str:
        return "automation_delete"

    def description(self) -> str:
        return "Delete an automation rule."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        auto = _require_automation(context, _require_string(input_data, "automation_id"))
        store = _automation_store(context)
        store["items"] = [a for a in store["items"] if a.id != auto.id]
        return ToolResult(
            success=True,
            content="deleted",
            metadata={"automation_id": auto.id},
        )


class AutomationRunTool(ToolSpec):
    def name(self) -> str:
        return "automation_run"

    def description(self) -> str:
        return "Manually trigger an automation rule."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"automation_id": {"type": "string"}},
            "required": ["automation_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        auto = _require_automation(context, _require_string(input_data, "automation_id"))
        return ToolResult(
            success=True,
            content=f"triggered: {auto.action}",
            metadata={"automation_id": auto.id, "action": auto.action},
        )


def _automation_store(context: ToolContext) -> dict[str, Any]:
    store = context.metadata.get(_AUTOMATION_STORE_KEY)
    if store is None:
        store = {"next_id": 1, "items": []}
        context.metadata[_AUTOMATION_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("automation store is invalid")
    items = store.get("items")
    next_id = store.get("next_id")
    if not isinstance(items, list) or not isinstance(next_id, int):
        raise ToolError("automation store is invalid")
    return store


def _require_automation(context: ToolContext, automation_id: str) -> Automation:
    for auto in _automation_store(context)["items"]:
        if isinstance(auto, Automation) and auto.id == automation_id:
            return auto
    raise ToolError(f"Unknown automation_id: {automation_id}")


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
