from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

_AGENT_STORE_KEY = "agents"


@dataclass(slots=True)
class SubAgent:
    id: str
    task: str
    status: str
    assignee: str = ""
    result: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


class AgentSpawnTool(ToolSpec):
    def name(self) -> str:
        return "agent_spawn"

    def description(self) -> str:
        return "Spawn a sub-agent to work on a task."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "assignee": {"type": "string"},
            },
            "required": ["task"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        task = _require_string(input_data, "task")
        assignee = _optional_string(input_data, "assignee") or ""
        store = _agent_store(context)
        agent = SubAgent(
            id=str(store["next_id"]),
            task=task,
            status="running",
            assignee=assignee,
        )
        store["next_id"] += 1
        store["items"].append(agent)
        return ToolResult(
            success=True,
            content=agent.id,
            metadata={"agent": asdict(agent)},
        )


class AgentResultTool(ToolSpec):
    def name(self) -> str:
        return "agent_result"

    def description(self) -> str:
        return "Submit a result for a running sub-agent."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "result": {"type": "string"},
            },
            "required": ["agent_id", "result"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        agent = _require_agent(context, _require_string(input_data, "agent_id"))
        agent.result = _require_string(input_data, "result")
        agent.status = "completed"
        return ToolResult(
            success=True,
            content="result submitted",
            metadata={"agent": asdict(agent)},
        )


class AgentAssignTool(ToolSpec):
    def name(self) -> str:
        return "agent_assign"

    def description(self) -> str:
        return "Assign or reassign a sub-agent to a different worker."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "assignee": {"type": "string"},
            },
            "required": ["agent_id", "assignee"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        agent = _require_agent(context, _require_string(input_data, "agent_id"))
        agent.assignee = _require_string(input_data, "assignee")
        return ToolResult(
            success=True,
            content="assigned",
            metadata={"agent": asdict(agent)},
        )


class AgentWaitTool(ToolSpec):
    def name(self) -> str:
        return "agent_wait"

    def description(self) -> str:
        return "Wait for a sub-agent to complete and return its result."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        agent = _require_agent(context, _require_string(input_data, "agent_id"))
        return ToolResult(
            success=True,
            content=agent.result or "(no result yet)",
            metadata={"agent": asdict(agent)},
        )


class AgentCancelTool(ToolSpec):
    def name(self) -> str:
        return "agent_cancel"

    def description(self) -> str:
        return "Cancel a running sub-agent."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        agent = _require_agent(context, _require_string(input_data, "agent_id"))
        agent.status = "cancelled"
        return ToolResult(
            success=True,
            content="cancelled",
            metadata={"agent": asdict(agent)},
        )


class AgentListTool(ToolSpec):
    def name(self) -> str:
        return "agent_list"

    def description(self) -> str:
        return "List all sub-agents."

    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        items = _agent_store(context)["items"]
        lines = [f"{a.id} | {a.status} | {a.task}" for a in items]
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={
                "agents": [asdict(a) for a in items],
                "count": len(items),
            },
        )


def _agent_store(context: ToolContext) -> dict[str, Any]:
    store = context.metadata.get(_AGENT_STORE_KEY)
    if store is None:
        store = {"next_id": 1, "items": []}
        context.metadata[_AGENT_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("agent store is invalid")
    items = store.get("items")
    next_id = store.get("next_id")
    if not isinstance(items, list) or not isinstance(next_id, int):
        raise ToolError("agent store is invalid")
    return store


def _require_agent(context: ToolContext, agent_id: str) -> SubAgent:
    for agent in _agent_store(context)["items"]:
        if isinstance(agent, SubAgent) and agent.id == agent_id:
            return agent
    raise ToolError(f"Unknown agent_id: {agent_id}")


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
