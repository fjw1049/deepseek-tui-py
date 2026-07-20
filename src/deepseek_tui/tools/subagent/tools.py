"""Sub-agent tools — thin wrappers over :class:`SubAgentManager`.

All 10 tools delegate
to ``context.subagent_manager``.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.subagent.types import (
    DEFAULT_RESULT_TIMEOUT_MS,
    MAX_RESULT_TIMEOUT_MS,
    MIN_WAIT_TIMEOUT_MS,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatusKind,
    SubAgentType,
    resolve_subagent_model,
)

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent.manager import SubAgentManager


def _require_manager(context: ToolContext) -> SubAgentManager:
    manager = context.subagent_manager
    if manager is None:
        raise ToolError("SubAgentManager is not attached to this context")
    return manager


def _spawn_runtime(context: ToolContext) -> Any | None:
    """Resolve SubAgentRuntime for the current caller.

    Nested sub-agents stash it on ``metadata['subagent_runtime']``. The parent
    Engine only attaches it to ``SubAgentManager.loop_runtime`` — fall back so
    per-type model routing and depth checks work on the main agent path.
    """
    nested = context.metadata.get("subagent_runtime")
    if nested is not None:
        return nested
    manager = context.subagent_manager
    if manager is None:
        return None
    return getattr(manager, "loop_runtime", None)


def _spawn_config(context: ToolContext) -> Any | None:
    runtime = _spawn_runtime(context)
    return getattr(runtime, "config", None) if runtime is not None else None


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


def _parse_wait_ids(data: dict[str, Any]) -> list[str]:
    """Collect wait targets from ``ids`` / ``agent_ids`` / ``agent_id`` / ``id``."""
    ids: list[str] = []
    for key in ("agent_ids", "ids"):
        raw = data.get(key)
        if not isinstance(raw, list):
            continue
        for value in raw:
            if isinstance(value, str):
                agent_id = value.strip()
                if agent_id and agent_id not in ids:
                    ids.append(agent_id)
    for key in ("agent_id", "id"):
        single = _pick_str(data, key)
        if single and single not in ids:
            ids.append(single)
    return ids


def _parse_wait_mode(data: dict[str, Any]) -> str:
    mode = _pick_str(data, "wait_mode", "mode") or "any"
    if mode not in ("any", "all", "first"):
        raise ToolError(f"Invalid wait_mode '{mode}'. Use: any, all, or first")
    return mode


def _running_agent_ids(manager: SubAgentManager) -> list[str]:
    return [
        snap.agent_id
        for snap in manager.list_filtered(include_archived=False)
        if snap.status.kind is SubAgentStatusKind.RUNNING
    ]


def _resolve_plugin_agent(raw_type: str, context: ToolContext) -> Any | None:
    """Look up a plugin-contributed persona by name (case-insensitive).

    Plugin agents are registered on the parent turn's ToolContext under
    ``metadata['plugin_agents']`` as a ``{name_lower: PluginAgent}`` map.
    When deferred assembly is active the map may be empty until the owning
    plugin is activated -- if the direct lookup misses, we check the
    ``plugin_agent_index`` (agent name -> plugin name, built from the
    lockfile index) and call ``activate_plugin`` to load that plugin's
    agents on demand, then retry.
    """
    key = raw_type.strip().lower()
    registry = context.metadata.get("plugin_agents")
    if isinstance(registry, dict):
        match = registry.get(key)
        if match is not None:
            return match
    # Deferred: activate the owning plugin, then retry.
    agent_index = context.metadata.get("plugin_agent_index")
    if isinstance(agent_index, dict):
        plugin_name = agent_index.get(key)
        if plugin_name is not None:
            activate = context.metadata.get("activate_plugin")
            if callable(activate):
                activate(plugin_name)
                registry = context.metadata.get("plugin_agents")
                if isinstance(registry, dict):
                    return registry.get(key)
    return None


class AgentSpawnTool(ToolSpec):
    def name(self) -> str:
        return "agent_spawn"

    def description(self) -> str:
        return (
            "Spawn a sub-agent for an independent investigation or implementation "
            "slice. Tool access is filtered by type (explore/review are read-only; "
            "plan cannot exec; implementer can edit). Default: the parent turn "
            "waits for completion via handoff / agent_wait. Set "
            "run_in_background=true only when you can continue without this "
            "result — completion arrives later as a <deepseek:subagent.done> "
            "reminder (do not poll). Prefer agent_wait/delegate when you need "
            "the result in this reply; use task_create only for work that must "
            "survive restarts and never re-enter this conversation."
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
                    "description": (
                        "Agent type. Built-in: general, explore, plan, review, "
                        "implementer, verifier, custom. Plugin-contributed "
                        "personas: prefer `plugin:persona` (or bare persona "
                        "name when unique) as listed under Plugin Agents."
                    ),
                },
                "agent_type": {
                    "type": "string",
                    "description": "Alias for type"
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
                "run_in_background": {
                    "type": "boolean",
                    "description": (
                        "When true, the parent turn does NOT block waiting for this "
                        "sub-agent. When the child finishes, the runtime injects a "
                        "<deepseek:subagent.done> system reminder (starting a new "
                        "turn if the parent is idle). Use only when you can continue "
                        "other work without this result; otherwise omit it and let "
                        "handoff / agent_wait collect the result in this turn."
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
        # A name that is not a built-in type may be a plugin-contributed
        # persona (Claude Code agents/<name>.md). Its markdown body becomes
        # the sub-agent's system prompt.
        plugin_persona = None
        persona_prompt: str | None = None
        if agent_type is None:
            plugin_persona = _resolve_plugin_agent(raw_type, context)
            if plugin_persona is None:
                valid_types = ", ".join([
                    "general", "explore", "plan", "review",
                    "implementer", "verifier", "custom"
                ])
                registry = context.metadata.get("plugin_agents")
                if isinstance(registry, dict) and registry:
                    plugin_names = sorted(
                        {
                            (
                                f"{getattr(a, 'plugin', '')}:{a.name}"
                                if getattr(a, "plugin", None)
                                else a.name
                            )
                            for a in registry.values()
                        }
                    )
                else:
                    # Deferred: fall back to the lockfile agent index.
                    agent_index = context.metadata.get("plugin_agent_index")
                    plugin_names = (
                        sorted(
                            k
                            for k in agent_index
                            if isinstance(k, str) and ":" in k
                        )
                        if isinstance(agent_index, dict)
                        else []
                    )
                extra = (
                    f" Plugin agents: {', '.join(plugin_names)}."
                    if plugin_names else ""
                )
                raise ToolError(
                    f"Unknown sub-agent type: {raw_type}. "
                    f"Valid types: {valid_types}.{extra} "
                    f"Use 'nickname' parameter for custom display names."
                )
            agent_type = SubAgentType.GENERAL
            from deepseek_tui.engine.prompts import substitute_builtin_template_vars

            persona_prompt = substitute_builtin_template_vars(plugin_persona.body)
        role = _pick_str(input_data, "role")
        allowed_raw = input_data.get("allowed_tools")
        allowed_tools: list[str] | None = None
        if isinstance(allowed_raw, list):
            allowed_tools = [s for s in allowed_raw if isinstance(s, str)]
        # Untrusted plugin personas cannot expand tools via frontmatter or by
        # inheriting the full GENERAL registry. Explicit caller allowed_tools
        # still win (parent agent opted in). When plugin_trust is absent
        # (standalone unit tests), treat as trusted for backward compatibility.
        plugin_trusted = True
        if plugin_persona is not None:
            trust_map = context.metadata.get("plugin_trust")
            if isinstance(trust_map, dict):
                owner = (getattr(plugin_persona, "plugin", None) or "").lower()
                plugin_trusted = bool(trust_map.get(owner, False))
        # Plugin persona frontmatter ``tools`` is advisory until applied here.
        # Map Claude/CodeBuddy names (Read/Grep/…) onto DeepSeek tool ids.
        if (
            plugin_trusted
            and not allowed_tools
            and plugin_persona is not None
            and getattr(plugin_persona, "tools", None)
        ):
            from deepseek_tui.integrations.plugin_compat import map_tool_matcher

            mapped: list[str] = []
            seen: set[str] = set()
            for tok in plugin_persona.tools:
                for name in map_tool_matcher(str(tok)):
                    if name not in seen:
                        seen.add(name)
                        mapped.append(name)
            if mapped:
                allowed_tools = mapped
        if (
            plugin_persona is not None
            and not plugin_trusted
            and not allowed_tools
        ):
            from deepseek_tui.engine.orchestrator.helpers import FOCUS_READ_BASE

            allowed_tools = sorted(FOCUS_READ_BASE)
        # NOTE: type-level default allowlist is applied in ``run_subagent_loop``
        # (not here) so direct ``manager.spawn`` callers (tests, delegate_to_agent,
        # workflow) get the same filtering as LLM-driven ``agent_spawn`` calls.
        if agent_type is SubAgentType.CUSTOM and not allowed_tools:
            raise ToolError("Custom sub-agents require a non-empty allowed_tools list")
        fork_context = _pick_bool(input_data, "fork_context")
        background = _pick_bool(input_data, "run_in_background")
        fork_messages = None
        if fork_context:
            raw = context.metadata.get("parent_session_messages")
            if isinstance(raw, list):
                fork_messages = [m for m in raw if isinstance(m, dict)]
        # Persona ``model`` is only applied when it looks like a DeepSeek id;
        # foreign labels (opus/sonnet/…) stay advisory and are ignored.
        persona_model = ""
        if plugin_persona is not None:
            persona_model = (getattr(plugin_persona, "model", None) or "").strip()
        user_model = _pick_str(input_data, "model")
        chosen_model = user_model
        if not chosen_model and persona_model.lower().startswith("deepseek"):
            chosen_model = persona_model
        if not chosen_model:
            cfg = _spawn_config(context)
            if cfg is not None:
                chosen_model = resolve_subagent_model(agent_type, cfg) or ""
        parent_raw = context.metadata.get("subagent_id")
        parent_agent_id = (
            parent_raw.strip()
            if isinstance(parent_raw, str) and parent_raw.strip()
            else None
        )
        request = SpawnRequest(
            prompt=prompt,
            agent_type=agent_type,
            assignment=SubAgentAssignment(objective=prompt, role=role),
            allowed_tools=allowed_tools,
            model=chosen_model,
            nickname=_pick_str(input_data, "nickname")
            or (plugin_persona.name if plugin_persona else None),
            parent_depth=int(context.metadata.get("subagent_depth", 0) or 0),
            parent_agent_id=parent_agent_id,
            fork_context=fork_context,
            fork_messages=fork_messages,
            system_prompt=persona_prompt,
            background=background,
        )
        runtime_raw = _spawn_runtime(context)
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
        content = f"spawned {snapshot.agent_id} [{snapshot.agent_type.value}]"
        if background:
            content += (
                " (background: completion is injected automatically when ready; "
                "do not wait or poll)"
            )
        return ToolResult(
            success=True,
            content=content,
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
        return (
            "Resume a cancelled/interrupted/failed sub-agent from its durable "
            "transcript checkpoint (skips completed tool rounds). Pass agent id. "
            "Do not spawn a new agent for the same work."
        )

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
        return (
            "Wait for one or more sub-agents to reach a terminal state. "
            "When no ids are given, waits on all currently running sub-agents."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Agent IDs to wait on. When omitted, waits on all running sub-agents.",
                },
                "agent_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alias for ids",
                },
                "agent_id": {"type": "string", "description": "Single agent ID"},
                "id": {"type": "string", "description": "Alias for agent_id"},
                "wait_mode": {
                    "type": "string",
                    "enum": ["any", "all", "first"],
                    "description": "Wait behavior: any (default), all, or first",
                },
                "mode": {
                    "type": "string",
                    "enum": ["any", "all", "first"],
                    "description": "Alias for wait_mode",
                },
                "timeout_ms": {"type": "integer"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        manager = _require_manager(context)
        mode = _parse_wait_mode(input_data)
        timeout_ms = _pick_int(input_data, "timeout_ms", default=DEFAULT_RESULT_TIMEOUT_MS)
        timeout_ms = max(
            MIN_WAIT_TIMEOUT_MS,
            min(MAX_RESULT_TIMEOUT_MS, int(timeout_ms or DEFAULT_RESULT_TIMEOUT_MS)),
        )
        agent_ids = _parse_wait_ids(input_data)
        if not agent_ids:
            agent_ids = _running_agent_ids(manager)
        if not agent_ids:
            empty: list[dict[str, Any]] = []
            return ToolResult(
                success=True,
                content=json.dumps(empty, ensure_ascii=False),
                metadata={
                    "wait_mode": mode,
                    "timed_out": False,
                    "timeout_ms": timeout_ms,
                    "waited_ids": [],
                    "agents": empty,
                },
            )
        try:
            snapshots = await manager.wait(agent_ids, mode=mode, timeout_ms=timeout_ms)
        except (KeyError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        payload = [_result_to_json(s) for s in snapshots]
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
            metadata={"agents": payload, "wait_mode": mode, "waited_ids": agent_ids},
        )


class DelegateToAgentTool(ToolSpec):
    """``delegate_to_agent`` — convenience combo: spawn + block on result.

    Internally spawns a fresh agent
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
