"""Sub-agent tools — thin wrappers over :class:`SubAgentManager`.

Mirrors Rust ``crates/tui/src/tools/subagent/mod.rs`` (3,604 lines).
All 10 tools delegate to ``context.subagent_manager``.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.subagent import (
    DEFAULT_RESULT_TIMEOUT_MS,
    MAX_RESULT_TIMEOUT_MS,
    MIN_WAIT_TIMEOUT_MS,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentResult,
    SubAgentType,
)


def _require_manager(context: ToolContext) -> SubAgentManager:
    manager = context.subagent_manager
    if manager is None:
        raise ToolError("SubAgentManager is not attached to this context")
    return manager


def _result_to_json(result: SubAgentResult) -> dict[str, Any]:
    return {
        "agent_id": result.agent_id,
        "agent_type": result.agent_type.value,
        "assignment": asdict(result.assignment),
        "model": result.model,
        "nickname": result.nickname,
        "status": result.status.to_dict(),
        "result": result.result,
        "steps_taken": result.steps_taken,
        "duration_ms": result.duration_ms,
        "from_prior_session": result.from_prior_session,
    }


def _pick_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _pick_bool(data: dict[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            return value
    return default


def _pick_int(data: dict[str, Any], *keys: str, default: int | None = None) -> int | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return default


class AgentSpawnTool(ToolSpec):
    def name(self) -> str:
        return "agent_spawn"

    def description(self) -> str:
        return (
            "Spawn a background sub-agent. Sub-agents run with a filtered "
            "toolset and inherit the workspace configuration from the session. "
            "Use 'type' parameter to specify agent type (general, implementer, etc.), "
            "and 'nickname' for custom display names."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The task prompt for the sub-agent"
                },
                "message": {
                    "type": "string",
                    "description": "Alias for prompt"
                },
                "objective": {
                    "type": "string",
                    "description": "Alias for prompt"
                },
                "type": {
                    "type": "string",
                    "description": "Agent type: general, explore, plan, review, implementer, verifier, custom",
                    "enum": ["general", "explore", "plan", "review", "implementer", "verifier", "custom"]
                },
                "agent_type": {
                    "type": "string",
                    "description": "Alias for type",
                    "enum": ["general", "explore", "plan", "review", "implementer", "verifier", "custom"]
                },
                "agent_name": {
                    "type": "string",
                    "description": "DEPRECATED: Use 'type' instead. This parameter is for backward compatibility only."
                },
                "role": {
                    "type": "string",
                    "description": "Optional role description for the agent"
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit tool allowlist (required for custom type)"
                },
                "model": {
                    "type": "string",
                    "description": "Optional model override (e.g., 'deepseek-chat', 'deepseek-v4-pro')"
                },
                "nickname": {
                    "type": "string",
                    "description": "Optional display name for the agent (does not affect agent type)"
                },
                "fork_context": {
                    "type": "boolean",
                    "description": (
                        "When true, inherit the parent's conversation prefix before "
                        "appending this task. Defaults to false for independent exploration."
                    ),
                },
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        prompt = _pick_str(input_data, "prompt", "message", "objective")
        if prompt is None:
            raise ToolError("prompt (or message/objective) is required")
        raw_type = _pick_str(input_data, "type", "agent_type", "agent_name") or "general"
        agent_type = SubAgentType.parse(raw_type)
        if agent_type is None:
            valid_types = ", ".join([
                "general", "explore", "plan", "review",
                "implementer", "verifier", "custom"
            ])
            raise ToolError(
                f"Unknown sub-agent type: {raw_type}. "
                f"Valid types: {valid_types}. "
                f"Use 'nickname' parameter for custom display names."
            )
        role = _pick_str(input_data, "role")
        allowed_raw = input_data.get("allowed_tools")
        allowed_tools: list[str] | None = None
        if isinstance(allowed_raw, list):
            allowed_tools = [s for s in allowed_raw if isinstance(s, str)]
        if agent_type is SubAgentType.CUSTOM and not allowed_tools:
            raise ToolError("Custom sub-agents require a non-empty allowed_tools list")
        fork_context = _pick_bool(input_data, "fork_context")
        fork_messages = None
        if fork_context:
            raw = context.metadata.get("parent_session_messages")
            if isinstance(raw, list):
                fork_messages = [m for m in raw if isinstance(m, dict)]
        request = SpawnRequest(
            prompt=prompt,
            agent_type=agent_type,
            assignment=SubAgentAssignment(objective=prompt, role=role),
            allowed_tools=allowed_tools,
            model=_pick_str(input_data, "model"),
            nickname=_pick_str(input_data, "nickname"),
            parent_depth=int(context.metadata.get("subagent_depth", 0) or 0),
            fork_context=fork_context,
            fork_messages=fork_messages,
        )
        runtime_raw = context.metadata.get("subagent_runtime")
        if runtime_raw is not None and hasattr(runtime_raw, "would_exceed_depth"):
            if runtime_raw.would_exceed_depth():
                raise ToolError(
                    f"Sub-agent depth limit reached (current depth "
                    f"{runtime_raw.spawn_depth}, max "
                    f"{runtime_raw.max_spawn_depth})"
                )
        try:
            snapshot = await manager.spawn(request)
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content=f"spawned {snapshot.agent_id} [{snapshot.agent_type.value}]",
            metadata=_result_to_json(snapshot),
        )


class AgentResultTool(ToolSpec):
    def name(self) -> str:
        return "agent_result"

    def description(self) -> str:
        return "Fetch result of a sub-agent; optionally block until complete."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "id": {"type": "string"},
                "block": {"type": "boolean"},
                "timeout_ms": {"type": "integer"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        agent_id = _pick_str(input_data, "agent_id", "id")
        if agent_id is None:
            raise ToolError("agent_id is required")
        block = _pick_bool(input_data, "block")
        timeout_ms = _pick_int(
            input_data, "timeout_ms", default=DEFAULT_RESULT_TIMEOUT_MS
        ) or DEFAULT_RESULT_TIMEOUT_MS
        timeout_ms = max(1000, min(MAX_RESULT_TIMEOUT_MS, int(timeout_ms)))
        try:
            if block:
                snapshots = await manager.wait([agent_id], mode="any", timeout_ms=timeout_ms)
                snapshot = snapshots[0]
            else:
                snapshot = await manager.get_result(agent_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        payload = _result_to_json(snapshot)
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
            metadata=payload,
        )


class AgentCancelTool(ToolSpec):
    def name(self) -> str:
        return "agent_cancel"

    def description(self) -> str:
        return "Cancel a running sub-agent."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        agent_id = _pick_str(input_data, "agent_id", "id")
        if agent_id is None:
            raise ToolError("agent_id is required")
        try:
            snapshot = await manager.cancel(agent_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content=f"cancelled {snapshot.agent_id}",
            metadata=_result_to_json(snapshot),
        )


class AgentCloseTool(ToolSpec):
    def name(self) -> str:
        return "close_agent"

    def description(self) -> str:
        return "Close a running sub-agent. Alias for agent_cancel."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        agent_id = _pick_str(input_data, "id", "agent_id")
        if agent_id is None:
            raise ToolError("id is required")
        try:
            snapshot = await manager.cancel(agent_id)
        except KeyError as exc:
            raise ToolError(str(exc)) from exc
        payload = _result_to_json(snapshot)
        payload["_deprecation"] = {
            "this_tool": "close_agent",
            "use_instead": "agent_cancel",
            "message": "Tool 'close_agent' is deprecated; switch to 'agent_cancel'.",
        }
        return ToolResult(
            success=True,
            content=f"cancelled {snapshot.agent_id}",
            metadata=payload,
        )


class AgentResumeTool(ToolSpec):
    def name(self) -> str:
        return "resume_agent"

    def description(self) -> str:
        return "Resume a terminated sub-agent."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        agent_id = _pick_str(input_data, "id", "agent_id")
        if agent_id is None:
            raise ToolError("id is required")
        try:
            snapshot = await manager.resume(agent_id)
        except (KeyError, RuntimeError) as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content=f"resumed {snapshot.agent_id}",
            metadata=_result_to_json(snapshot),
        )


class AgentListTool(ToolSpec):
    def name(self) -> str:
        return "agent_list"

    def description(self) -> str:
        return "List sub-agents; include_archived flips prior-session filter."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_archived": {"type": "boolean"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        include_archived = _pick_bool(input_data, "include_archived")
        snapshots = manager.list_filtered(include_archived=include_archived)
        return ToolResult(
            success=True,
            content=f"{len(snapshots)} agent(s)",
            metadata={"agents": [_result_to_json(s) for s in snapshots]},
        )


class AgentSendInputTool(ToolSpec):
    def name(self) -> str:
        return "agent_send_input"

    def description(self) -> str:
        return "Send a text input to a running sub-agent."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "id": {"type": "string"},
                "input": {"type": "string"},
                "text": {"type": "string"},
                "interrupt": {"type": "boolean"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        agent_id = _pick_str(input_data, "agent_id", "id")
        text = _pick_str(input_data, "input", "text")
        if agent_id is None or text is None:
            raise ToolError("agent_id and input are required")
        interrupt = _pick_bool(input_data, "interrupt")
        try:
            await manager.send_input(agent_id, text, interrupt=interrupt)
        except (KeyError, RuntimeError) as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content=f"sent input to {agent_id}",
            metadata={"agent_id": agent_id, "interrupt": interrupt},
        )


class AgentAssignTool(ToolSpec):
    def name(self) -> str:
        return "agent_assign"

    def description(self) -> str:
        return "Update a sub-agent's objective/role and optionally inject a message."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "id": {"type": "string"},
                "objective": {"type": "string"},
                "role": {"type": "string"},
                "message": {"type": "string"},
                "interrupt": {"type": "boolean"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        agent_id = _pick_str(input_data, "agent_id", "id")
        if agent_id is None:
            raise ToolError("agent_id is required")
        try:
            snapshot = await manager.assign(
                agent_id,
                objective=_pick_str(input_data, "objective"),
                role=_pick_str(input_data, "role"),
                message=_pick_str(input_data, "message"),
                interrupt=_pick_bool(input_data, "interrupt"),
            )
        except (KeyError, RuntimeError) as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            success=True,
            content=f"reassigned {snapshot.agent_id}",
            metadata=_result_to_json(snapshot),
        )


class AgentWaitTool(ToolSpec):
    def name(self) -> str:
        return "agent_wait"

    def description(self) -> str:
        return "Wait for one or more sub-agents to reach a terminal state."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_ids": {"type": "array", "items": {"type": "string"}},
                "agent_id": {"type": "string"},
                "mode": {"type": "string", "enum": ["any", "all", "first"]},
                "timeout_ms": {"type": "integer"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        ids_raw = input_data.get("agent_ids")
        agent_ids: list[str]
        if isinstance(ids_raw, list) and ids_raw:
            agent_ids = [s for s in ids_raw if isinstance(s, str)]
        else:
            single = _pick_str(input_data, "agent_id", "id")
            if single is None:
                raise ToolError("agent_ids or agent_id is required")
            agent_ids = [single]
        mode = _pick_str(input_data, "mode") or "any"
        timeout_ms = _pick_int(input_data, "timeout_ms", default=DEFAULT_RESULT_TIMEOUT_MS)
        timeout_ms = max(
            MIN_WAIT_TIMEOUT_MS,
            min(MAX_RESULT_TIMEOUT_MS, int(timeout_ms or DEFAULT_RESULT_TIMEOUT_MS)),
        )
        try:
            snapshots = await manager.wait(agent_ids, mode=mode, timeout_ms=timeout_ms)
        except (KeyError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        payload = [_result_to_json(s) for s in snapshots]
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
            metadata={"agents": payload},
        )


class DelegateToAgentTool(ToolSpec):
    """``delegate_to_agent`` — convenience combo: spawn + block on result.

    Mirrors Rust ``DelegateToAgentTool``; internally spawns a fresh agent
    then waits up to ``timeout_ms`` for it to terminate.
    """

    def name(self) -> str:
        return "delegate_to_agent"

    def description(self) -> str:
        return "Spawn a sub-agent and wait for its completion."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "message": {"type": "string"},
                "objective": {"type": "string"},
                "type": {"type": "string"},
                "agent_type": {"type": "string"},
                "role": {"type": "string"},
                "model": {"type": "string"},
                "allowed_tools": {"type": "array", "items": {"type": "string"}},
                "timeout_ms": {"type": "integer"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        spawn_result = await AgentSpawnTool().execute(input_data, context)
        agent_id = spawn_result.metadata["agent_id"]
        timeout_ms = _pick_int(
            input_data, "timeout_ms", default=DEFAULT_RESULT_TIMEOUT_MS
        ) or DEFAULT_RESULT_TIMEOUT_MS
        wait_input = {"agent_id": agent_id, "mode": "any", "timeout_ms": timeout_ms}
        wait_result = await AgentWaitTool().execute(wait_input, context)
        final = wait_result.metadata["agents"][0]
        return ToolResult(
            success=True,
            content=f"delegated to {agent_id} → {final['status']['kind']}",
            metadata=final,
        )
