"""Sub-agent tools — thin wrappers over :class:`SubAgentManager`.

One tool is registered with the ToolRegistry:

- ``agent`` (:class:`AgentTool`) — a single action-dispatched tool covering
  spawn / send_input / wait, plus a ``resume`` parameter (mutually exclusive
  with ``action``) that resumes a cancelled or interrupted sub-agent from
  its durable checkpoint. The retired ``agent_resume`` tool name is still
  accepted at the execution layer and forwarded here (see
  ``engine.dispatch.normalize_legacy_tool_call``).

The retired ``list`` / ``result`` / ``cancel`` actions are also forwarded at
the execution layer — to ``task_list`` / ``task_output`` / ``task_stop``,
which now own background-entity inspection and stopping. Their handler
functions (``_execute_result`` / ``_execute_cancel``) stay here and are
reused by those task tools.

Delegates to ``context.subagent_manager``.
"""

from __future__ import annotations

import json
import logging
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
    from collections.abc import Callable, Iterable

    from deepseek_tui.tools.subagent.manager import SubAgentManager

logger = logging.getLogger(__name__)


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


def _pick_str_aliased(data: dict[str, Any], canonical: str, *aliases: str) -> str | None:
    """Pick ``canonical`` first; fall back to legacy aliases (debug-logged)."""
    value = _pick_str(data, canonical)
    if value is not None:
        return value
    for alias in aliases:
        value = _pick_str(data, alias)
        if value is not None:
            logger.debug("agent tool: legacy alias %r used for %r", alias, canonical)
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
    """Collect wait targets from ``agent_ids`` (canonical) or legacy aliases."""
    ids: list[str] = []
    raw = data.get("agent_ids")
    if not isinstance(raw, list):
        if "ids" in data:
            logger.debug("agent tool: legacy alias 'ids' used for 'agent_ids'")
        raw = data.get("ids")
    if isinstance(raw, list):
        for value in raw:
            if isinstance(value, str):
                agent_id = value.strip()
                if agent_id and agent_id not in ids:
                    ids.append(agent_id)
    single = _pick_str(data, "agent_id")
    if single is None:
        single = _pick_str(data, "id")
        if single is not None:
            logger.debug("agent tool: legacy alias 'id' used for 'agent_id'")
    if single and single not in ids:
        ids.append(single)
    return ids


def _parse_wait_mode(data: dict[str, Any]) -> str:
    mode = _pick_str_aliased(data, "wait_mode", "mode") or "any"
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


# ---------------------------------------------------------------------------
# Action implementations (shared by AgentTool dispatch)
# ---------------------------------------------------------------------------


async def _execute_spawn(input_data: dict[str, Any], context: ToolContext) -> ToolResult:
    manager = _require_manager(context)
    prompt = _pick_str_aliased(input_data, "prompt", "message", "objective")
    if prompt is None:
        raise ToolError("agent action 'spawn' requires 'prompt'")
    raw_type = (
        _pick_str_aliased(input_data, "agent_type", "type", "agent_name") or "general"
    )
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
    # (not here) so direct ``manager.spawn`` callers (tests, workflow) get
    # the same filtering as LLM-driven ``agent`` spawn calls.
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


async def _execute_result(input_data: dict[str, Any], context: ToolContext) -> ToolResult:
    """Fetch a sub-agent result or background-process output.

    Retired as an ``agent`` action; reused by ``task_output`` (and by the
    execution-layer forwarding of the old action).
    """
    block = _pick_bool(input_data, "block")
    timeout_ms = _pick_int(
        input_data, "timeout_ms", default=DEFAULT_RESULT_TIMEOUT_MS
    ) or DEFAULT_RESULT_TIMEOUT_MS
    timeout_ms = max(1000, min(MAX_RESULT_TIMEOUT_MS, int(timeout_ms)))
    process_id = _pick_str(input_data, "process_id")
    if process_id is not None:
        if _pick_str_aliased(input_data, "agent_id", "id") is not None:
            raise ToolError("pass either agent_id or process_id, not both")
        # Background shell process — route to the shell process store.
        from deepseek_tui.tools import shell as _shell

        if block:
            return await _shell.wait_background_process(
                context, process_id, timeout_ms=timeout_ms
            )
        return await _shell.peek_background_process(context, process_id)
    agent_id = _pick_str_aliased(input_data, "agent_id", "id")
    if agent_id is None:
        raise ToolError("result fetch requires 'agent_id' or 'process_id'")
    manager = _require_manager(context)
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


async def _execute_cancel(input_data: dict[str, Any], context: ToolContext) -> ToolResult:
    process_id = _pick_str(input_data, "process_id")
    if process_id is not None:
        if _pick_str_aliased(input_data, "agent_id", "id") is not None:
            raise ToolError("pass either agent_id or process_id, not both")
        from deepseek_tui.tools import shell as _shell

        return await _shell.cancel_background_process(context, process_id)
    agent_id = _pick_str_aliased(input_data, "agent_id", "id")
    if agent_id is None:
        raise ToolError("cancel requires 'agent_id' or 'process_id'")
    manager = _require_manager(context)
    try:
        snapshot = await manager.cancel(agent_id)
    except KeyError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(
        success=True,
        content=f"cancelled {snapshot.agent_id}",
        metadata=_result_to_json(snapshot),
    )


async def _execute_send_input(
    input_data: dict[str, Any], context: ToolContext
) -> ToolResult:
    manager = _require_manager(context)
    agent_id = _pick_str_aliased(input_data, "agent_id", "id")
    text = _pick_str_aliased(input_data, "input", "text")
    if agent_id is None or text is None:
        raise ToolError("agent action 'send_input' requires 'agent_id' and 'input'")
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


async def _execute_wait(input_data: dict[str, Any], context: ToolContext) -> ToolResult:
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


# ---------------------------------------------------------------------------
# Registered tools
# ---------------------------------------------------------------------------

_ACTION_HANDLERS: dict[str, Callable[..., Any]] = {
    "spawn": _execute_spawn,
    "send_input": _execute_send_input,
    "wait": _execute_wait,
}

ALL_AGENT_ACTIONS: tuple[str, ...] = tuple(_ACTION_HANDLERS)

# Retired actions — forwarded at the execution layer
# (``engine.dispatch.normalize_legacy_tool_call``); direct calls get a
# steering error naming the replacement tool.
_RETIRED_ACTION_TARGETS: dict[str, str] = {
    "list": "task_list",
    "result": "task_output",
    "cancel": "task_stop",
}

# Read-path actions: registered in plan mode and exempt from approval prompts
# (matches the pre-merge agent_wait tool).
READ_AGENT_ACTIONS: tuple[str, ...] = ("wait",)

# Plan mode: inspect running agents, but never spawn, steer, or stop them
# (listing/reading/stopping background work moved to task_list/task_output/
# task_stop; task_stop is a side effect and stays out of plan mode — D5).
PLAN_AGENT_ACTIONS: tuple[str, ...] = ("wait",)

_ACTION_CAPABILITIES: dict[str, tuple[ToolCapability, ...]] = {
    "spawn": (ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL),
    "send_input": (ToolCapability.EXECUTES_CODE,),
    "wait": (ToolCapability.READ_ONLY,),
}

_ACTION_BLURBS: dict[str, str] = {
    "spawn": (
        "spawn: start a sub-agent for an independent investigation or "
        "implementation slice (requires 'prompt'; optional 'agent_type' — "
        "built-in: general, explore, plan, review, implementer, verifier, "
        "custom, or a plugin persona as '<plugin>:<name>' — plus 'role', "
        "'allowed_tools', 'model', 'nickname', 'fork_context', "
        "'run_in_background'). Default: the parent turn waits for completion "
        "via handoff / action='wait'. Set run_in_background=true only when "
        "you can continue without this result — completion arrives later as "
        "a <deepseek:subagent.done> reminder (do not poll)."
    ),
    "send_input": (
        "send_input: send a text 'input' to a running sub-agent "
        "(requires 'agent_id' and 'input'; optional 'interrupt')."
    ),
    "wait": (
        "wait: wait for one or more sub-agents to reach a terminal state "
        "('agent_ids' list or a single 'agent_id'; 'wait_mode' any/all/"
        "first, default any; 'timeout_ms'). With no ids, waits on all "
        "currently running sub-agents."
    ),
}


class AgentTool(ToolSpec):
    """Single action-dispatched sub-agent tool.

    ``allowed_actions`` controls which actions the instance exposes: the
    ``action`` enum is generated from it, so a plan-mode registry can offer
    the read/cancel subset without any runtime mode checks in execute.

    ``allow_resume`` controls whether the ``resume`` parameter (restart a
    cancelled/interrupted/failed sub-agent from its durable checkpoint)
    appears in the schema and is accepted by execute. Plan mode disables
    it: resume restarts real work, which read-only plan mode must not do.
    """

    def __init__(
        self,
        allowed_actions: Iterable[str] | None = None,
        *,
        allow_resume: bool = True,
    ) -> None:
        actions = tuple(allowed_actions) if allowed_actions is not None else ALL_AGENT_ACTIONS
        unknown = [a for a in actions if a not in _ACTION_HANDLERS]
        if unknown:
            raise ValueError(f"unknown agent action(s): {', '.join(unknown)}")
        self._allowed_actions = actions
        self._allow_resume = allow_resume

    def name(self) -> str:
        return "agent"

    def description(self) -> str:
        blurbs = "; ".join(_ACTION_BLURBS[a] for a in self._allowed_actions)
        text = (
            f"Manage sub-agents. Actions — {blurbs}. To list agents, fetch "
            "their results, or stop them (and durable tasks / background "
            "shell processes), use the task_list / task_output / task_stop "
            "tools instead"
        )
        if self._allow_resume:
            text += (
                ". Alternatively, pass 'resume' with a sub-agent id (and no "
                "'action' — the two are mutually exclusive) to resume a "
                "cancelled/interrupted/failed sub-agent from its durable "
                "transcript checkpoint, skipping completed tool rounds. Do "
                "not spawn a new agent for the same work."
            )
        return text

    def input_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(self._allowed_actions),
                    "description": (
                        "Which sub-agent operation to perform."
                        + (
                            " Required unless 'resume' is given."
                            if self._allow_resume
                            else ""
                        )
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": "The task prompt for the sub-agent (action=spawn)",
                },
                "agent_type": {
                    "type": "string",
                    "description": (
                        "Agent type (action=spawn). Built-in: general, explore, "
                        "plan, review, implementer, verifier, custom. "
                        "Plugin-contributed personas: prefer `plugin:persona` "
                        "(or bare persona name when unique) as listed under "
                        "Plugin Agents."
                    ),
                },
                "role": {
                    "type": "string",
                    "description": "Optional role description for the agent (action=spawn)",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Explicit tool allowlist (action=spawn; required for "
                        "custom type)"
                    ),
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Optional model override (action=spawn; e.g., "
                        "'deepseek-chat', 'deepseek-v4-pro')"
                    ),
                },
                "nickname": {
                    "type": "string",
                    "description": (
                        "Optional display name for the agent (action=spawn; "
                        "does not affect agent type)"
                    ),
                },
                "fork_context": {
                    "type": "boolean",
                    "description": (
                        "When true (action=spawn), inherit the parent's "
                        "conversation prefix before appending this task. "
                        "Defaults to false for independent exploration."
                    ),
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": (
                        "When true (action=spawn), the parent turn does NOT "
                        "block waiting for this sub-agent. When the child "
                        "finishes, the runtime injects a "
                        "<deepseek:subagent.done> system reminder (starting a "
                        "new turn if the parent is idle). Use only when you "
                        "can continue other work without this result; "
                        "otherwise omit it and let handoff / action='wait' "
                        "collect the result in this turn."
                    ),
                },
                "agent_id": {
                    "type": "string",
                    "description": (
                        "Target sub-agent id (action=send_input/wait)"
                    ),
                },
                "agent_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Agent IDs to wait on (action=wait). When omitted, "
                        "waits on all running sub-agents."
                    ),
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": "Wait timeout in milliseconds (action=wait)",
                },
                "input": {
                    "type": "string",
                    "description": "Text to send (action=send_input)",
                },
                "interrupt": {
                    "type": "boolean",
                    "description": "Interrupt current work (action=send_input)",
                },
                "wait_mode": {
                    "type": "string",
                    "enum": ["any", "all", "first"],
                    "description": "Wait behavior (action=wait): any (default), all, or first",
                },
            },
            "required": ["action"],
        }
        if self._allow_resume:
            schema["properties"]["resume"] = {
                "type": "string",
                "description": (
                    "Resume a cancelled/interrupted/failed sub-agent by id, "
                    "restarting it from its durable transcript checkpoint "
                    "(completed tool rounds are skipped). Mutually exclusive "
                    "with 'action' — pass only one."
                ),
            }
            # 'action' stays effectively required, but 'resume' is the
            # alternative — enforced in execute(), not the schema.
            schema["required"] = []
        return schema

    def capabilities(self) -> list[ToolCapability]:
        # Union of the per-action capabilities this instance exposes.
        caps: list[ToolCapability] = []
        for action in self._allowed_actions:
            for cap in _ACTION_CAPABILITIES[action]:
                if cap not in caps:
                    caps.append(cap)
        return caps

    def approval_requirement_for_input(
        self, input_data: dict[str, Any]
    ) -> ApprovalRequirement:
        # Resume restarts real work — keep the retired agent_resume tool's
        # REQUIRED gate.
        if _pick_str(input_data, "resume") is not None:
            return ApprovalRequirement.REQUIRED
        # Read actions keep the pre-merge agent_result/agent_list/agent_wait
        # behavior: no approval prompt.
        action = input_data.get("action")
        if isinstance(action, str) and action.strip() in READ_AGENT_ACTIONS:
            return ApprovalRequirement.AUTO
        return self.approval_requirement()

    def is_read_only_for_input(self, input_data: dict[str, Any]) -> bool:
        # Static capabilities are the union across actions (they include
        # READ_ONLY), which would mark even spawn parallel-safe; decide per
        # call instead.
        action = input_data.get("action")
        return isinstance(action, str) and action.strip() in READ_AGENT_ACTIONS

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        raw_action = input_data.get("action")
        action = raw_action.strip() if isinstance(raw_action, str) else ""
        resume_id = _pick_str(input_data, "resume")
        if resume_id is not None:
            if not self._allow_resume:
                raise ToolError("agent resume is not available in this mode")
            if action:
                raise ToolError(
                    "'resume' is mutually exclusive with 'action' — pass only one"
                )
            return await _execute_resume(resume_id, context)
        if not action:
            raise ToolError(
                "agent action is required (one of: "
                + ", ".join(self._allowed_actions)
                + (")" if not self._allow_resume else "), or pass 'resume'")
            )
        handler = _ACTION_HANDLERS.get(action)
        if handler is None or action not in self._allowed_actions:
            if action in _RETIRED_ACTION_TARGETS:
                raise ToolError(
                    f"agent action '{action}' was retired — use "
                    f"{_RETIRED_ACTION_TARGETS[action]} instead"
                )
            raise ToolError(
                f"unknown agent action '{action}'. Allowed: "
                + ", ".join(self._allowed_actions)
            )
        return await handler(input_data, context)


async def _execute_resume(agent_id: str, context: ToolContext) -> ToolResult:
    """Resume a sub-agent from its durable checkpoint (true-resume).

    Shared by ``AgentTool`` (``resume`` parameter) and the execution-layer
    forwarding of the retired ``agent_resume`` tool name.
    """
    manager = _require_manager(context)
    try:
        snapshot = await manager.resume(agent_id)
    except (KeyError, RuntimeError) as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(
        success=True,
        content=f"resumed {snapshot.agent_id}",
        metadata=_result_to_json(snapshot),
    )

