"""Sub-agent spawning, communication, and delegation.

Consolidates subagent_tools.py and subagent/ package.
"""

from __future__ import annotations



# Sub-agent tools — thin wrappers over :class:`SubAgentManager`.
#
# Mirrors Rust ``crates/tui/src/tools/subagent/mod.rs`` (3,604 lines).
# All 10 tools delegate to ``context.subagent_manager``.
#
import json
from dataclasses import asdict
from typing import Any

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext


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


# Sub-agent runtime and manager.
#
# Mirrors `crates/tui/src/tools/subagent/mod.rs` (3,604 lines). Provides:
#
# - :class:`SubAgentType` / :class:`SubAgentStatus` / :class:`SubAgentResult`
# - :class:`SubAgentManager`: spawn/cancel/result/list/resume/assign/send_input
# - ``asyncio.Task``-backed execution (not multiprocessing — LLM calls are
#   IO-bound; see HANDOVER.md decision 2026-05-07)
# - Persistence under ``<workspace>/.deepseek/subagents.v1.json``
#
# The executor that drives the LLM loop is plugged in at manager
# construction; the default is a placeholder that sleeps briefly and
# returns a synthetic result (integration debt tracked for Stage 4).
#
import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.config.models import Config

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message


logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 100
DEFAULT_MAX_AGENTS = 10
DEFAULT_MAX_SPAWN_DEPTH = 3
_MAX_TERMINAL_AGENTS_IN_MEMORY = 30
# Upper bound for the final result we surface on the Workbench sub-agent card.
# The previous 500-char cap chopped real reports mid-sentence; the card detail
# dialog is the user's only window onto a sub-agent's deliverable, so keep it
# generous while still bounding pathological outputs.
_MAX_CARD_RESULT_CHARS = 16_000
DEFAULT_RESULT_TIMEOUT_MS = 180_000
MIN_WAIT_TIMEOUT_MS = 30_000
MAX_RESULT_TIMEOUT_MS = 3_600_000
SUBAGENT_STATE_SCHEMA_VERSION = 1
SUBAGENT_STATE_FILE = "subagents.v1.json"
SUBAGENT_RESTART_REASON = "Interrupted by process restart"


class SubAgentType(str, Enum):
    GENERAL = "general"
    EXPLORE = "explore"
    PLAN = "plan"
    REVIEW = "review"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    CUSTOM = "custom"

    @staticmethod
    def parse(raw: str) -> SubAgentType | None:
        """Accepts Rust-compatible aliases (general_purpose, worker, etc.)."""
        key = raw.strip().lower().replace("-", "_")
        aliases: dict[str, SubAgentType] = {
            "general": SubAgentType.GENERAL,
            "general_purpose": SubAgentType.GENERAL,
            "worker": SubAgentType.GENERAL,
            "default": SubAgentType.GENERAL,
            "explore": SubAgentType.EXPLORE,
            "exploration": SubAgentType.EXPLORE,
            "explorer": SubAgentType.EXPLORE,
            "plan": SubAgentType.PLAN,
            "planning": SubAgentType.PLAN,
            "awaiter": SubAgentType.PLAN,
            "review": SubAgentType.REVIEW,
            "code_review": SubAgentType.REVIEW,
            "reviewer": SubAgentType.REVIEW,
            "implementer": SubAgentType.IMPLEMENTER,
            "implement": SubAgentType.IMPLEMENTER,
            "implementation": SubAgentType.IMPLEMENTER,
            "builder": SubAgentType.IMPLEMENTER,
            "verifier": SubAgentType.VERIFIER,
            "verify": SubAgentType.VERIFIER,
            "verification": SubAgentType.VERIFIER,
            "validator": SubAgentType.VERIFIER,
            "tester": SubAgentType.VERIFIER,
            "custom": SubAgentType.CUSTOM,
        }
        return aliases.get(key)

    def system_prompt(self) -> str:
        """Return the system prompt for this agent type.

        Mirrors Rust ``SubAgentType::system_prompt`` (mod.rs:227-237).
        """
        from deepseek_tui.engine.prompts import load_prompt

        output_contract = load_prompt("subagent_output_format")
        base = _SUBAGENT_PROMPTS.get(self.value, "")
        return f"{base}\n\n{output_contract}" if base else output_contract


_SUBAGENT_PROMPTS: dict[str, str] = {
    "general": (
        "You are a general-purpose sub-agent spawned to handle a specific task autonomously.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Your scope is exactly what the parent assigned to you. Do not expand the\n"
        "objective — if you discover related work that needs doing, surface it under\n"
        "RISKS or BLOCKERS rather than starting it. Work autonomously: the parent is\n"
        "not available to answer questions mid-run.\n\n"
        "Plan before you act. Use `checklist_write` for any multi-step task so your work\n"
        "is visible in the parent's sidebar. For complex initiatives, layer\n"
        "`update_plan` (strategy) above `checklist_write` (tactics)."
    ),
    "explore": (
        "You are an exploration sub-agent. Your job is to map the relevant region\n"
        "of the codebase fast and report what is there. You are read-only by\n"
        "convention — do not write, patch, or run side-effectful commands. If the\n"
        "task seems to require a write, stop and put it under BLOCKERS.\n\n"
        "Method:\n"
        "- Start with `list_dir` and `file_search` to orient.\n"
        "- Use `grep_files` (NOT `exec_shell rg`) to find call sites, type defs,\n"
        "  and string literals. Prefer narrow, structured queries over broad scans.\n"
        "- Read each candidate file with `read_file`. Skim, then quote line ranges.\n"
        "- Stop reading once you have enough evidence — exhaustive sweeps are not\n"
        "  the goal. The parent will spawn a follow-up explorer if needed.\n\n"
        "EVIDENCE is the load-bearing section for explorers. Cite every file you\n"
        "read with `path:line-range` and one line per finding.\n\n"
        "CHANGES will almost always be \"None.\" for an explorer."
    ),
    "plan": (
        "You are a planning sub-agent. Your job is to take an objective and\n"
        "produce a prioritized, executable plan — not to execute it. Keep writes\n"
        "to a minimum (notes and plan artifacts only); avoid patches and shell\n"
        "side effects.\n\n"
        "Method:\n"
        "- Read enough of the codebase to ground the plan in reality.\n"
        "- Decompose the objective into ordered, verifiable steps.\n"
        "- Surface trade-offs explicitly. If two approaches are viable, name both\n"
        "  and pick one with a reason.\n"
        "- Use `update_plan` to record the strategy and `checklist_write` for the backlog.\n\n"
        "Prioritization: order todos by dependency graph first, then by risk/effort ratio.\n"
        "Tag each item with `[P0]` / `[P1]` / `[P2]`."
    ),
    "review": (
        "You are a code review sub-agent. Your job is to read the code under\n"
        "review and emit a severity-scored list of findings. You are read-only by\n"
        "convention — do not patch the code.\n\n"
        "For each finding, score severity: BLOCKER / MAJOR / MINOR / NIT.\n"
        "Order EVIDENCE bullets by severity, BLOCKER first.\n\n"
        "CHANGES will almost always be \"None.\" for a reviewer."
    ),
    "implementer": (
        "You are an implementation sub-agent. Your job is to land the change\n"
        "the parent assigned — write the code, modify the files, satisfy the\n"
        "contract — with the minimum surrounding edit. Do not refactor adjacent code.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Method:\n"
        "- Read target file(s) end-to-end before editing.\n"
        "- Prefer `edit_file` for narrow changes, `apply_patch` for multi-hunk.\n"
        "- After edits, run a quick verification (lint/test).\n"
        "- If tests are needed, write them alongside the implementation.\n\n"
        "CHANGES is the load-bearing section — list every file modified with a one-line summary."
    ),
    "verifier": (
        "You are a verification sub-agent. Your job is to run the project's\n"
        "test suite and report pass/fail with evidence. You are read-only —\n"
        "do not patch failing tests or modify code.\n\n"
        "Method:\n"
        "- Run the right gate: `run_tests`, or `exec_shell` for custom commands.\n"
        "- Capture the exact failing assertion plus stack trace in EVIDENCE.\n\n"
        "OUTCOME goes at the top of SUMMARY: PASS / FAIL / FLAKY.\n\n"
        "CHANGES will almost always be \"None.\" for a verifier."
    ),
    "custom": (
        "You are a custom sub-agent. The parent has given you a narrowed tool\n"
        "registry — only the tools you see at runtime are available. Do not try\n"
        "to reach for a tool that is not registered; if the task needs one, put\n"
        "the gap under BLOCKERS and stop.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Stay tightly scoped to the assigned objective."
    ),
}


_WHALE_NICKNAMES: tuple[str, ...] = (
    "Blue",
    "Humpback",
    "Sperm",
    "Orca",
    "Beluga",
    "Narwhal",
    "Pilot",
    "Minke",
)


def whale_nickname_for_index(index: int) -> str:
    base = _WHALE_NICKNAMES[index % len(_WHALE_NICKNAMES)]
    if index < len(_WHALE_NICKNAMES):
        return base
    return f"{base} {index // len(_WHALE_NICKNAMES) + 1}"


def build_subagent_system_prompt(
    agent_type: SubAgentType, assignment: SubAgentAssignment
) -> str:
    """Mirror Rust ``build_subagent_system_prompt`` (mod.rs:2629)."""
    base = agent_type.system_prompt()
    role = (assignment.role or "").strip()
    if role:
        return f"{base}\n\nYou are operating in the role of `{role}`."
    return base


class SubAgentStatusKind(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True, frozen=True)
class SubAgentStatus:
    kind: SubAgentStatusKind
    message: str | None = None

    @staticmethod
    def running() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.RUNNING)

    @staticmethod
    def completed() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.COMPLETED)

    @staticmethod
    def interrupted(msg: str) -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.INTERRUPTED, msg)

    @staticmethod
    def failed(msg: str) -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.FAILED, msg)

    @staticmethod
    def cancelled() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.CANCELLED)

    def is_terminal(self) -> bool:
        return self.kind is not SubAgentStatusKind.RUNNING

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind.value}
        if self.message is not None:
            out["message"] = self.message
        return out

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SubAgentStatus:
        return SubAgentStatus(
            SubAgentStatusKind(data["kind"]), data.get("message")
        )


@dataclass(slots=True)
class SubAgentAssignment:
    objective: str
    role: str | None = None


@dataclass(slots=True)
class SubAgentResult:
    agent_id: str
    agent_type: SubAgentType
    assignment: SubAgentAssignment
    model: str
    nickname: str | None
    status: SubAgentStatus
    result: str | None
    steps_taken: int
    duration_ms: int
    from_prior_session: bool = False
    structured: Any | None = None


@dataclass(slots=True)
class SpawnRequest:
    prompt: str
    agent_type: SubAgentType
    assignment: SubAgentAssignment
    allowed_tools: list[str] | None = None
    model: str | None = None
    nickname: str | None = None
    parent_depth: int = 0
    fork_context: bool = False
    fork_messages: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | None = None
    auto_approve: bool | None = None


# Executor signature — takes a SubAgent handle plus cancel token.
# Forward reference — AgentRunOutput defined later in this file
SubAgentExecutor = Callable  # type: ignore[assignment]


async def _stub_executor(agent: SubAgent, cancel: asyncio.Event) -> AgentRunOutput:
    """Placeholder executor — sleeps briefly, returns synthetic summary."""
    try:
        await asyncio.wait_for(cancel.wait(), timeout=0.05)
    except asyncio.TimeoutError:
        agent.steps_taken += 1
        text = f"[stub] agent {agent.id} completed prompt '{agent.prompt[:80]}'"
        return AgentRunOutput(text=text, structured=None)
    raise asyncio.CancelledError


def get_real_subagent_executor() -> SubAgentExecutor:
    """Return the real sub-agent executor that drives Engine turn loops."""
    from deepseek_tui.engine.dispatch import real_subagent_executor

    return real_subagent_executor


class SubAgent:
    """Single sub-agent handle.

    Mirrors Rust ``SubAgent`` (mod.rs:648-723).
    """

    def __init__(
        self,
        agent_type: SubAgentType,
        prompt: str,
        assignment: SubAgentAssignment,
        model: str,
        nickname: str | None,
        allowed_tools: list[str] | None,
        session_boot_id: str,
        workspace: Path | None = None,
        spawn_depth: int = 0,
        fork_messages: list[dict[str, Any]] | None = None,
        parent_cancel: asyncio.Event | None = None,
        mailbox: Mailbox | None = None,
        loop_runtime: SubAgentRuntime | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        self.id: str = f"agent_{uuid.uuid4().hex[:8]}"
        self.agent_type = agent_type
        self.prompt = prompt
        self.assignment = assignment
        self.model = model
        self.nickname = nickname
        self.status: SubAgentStatus = SubAgentStatus.running()
        self.result: str | None = None
        self.structured_result: Any | None = None
        self.output_schema = output_schema
        self.steps_taken: int = 0
        self.started_at_ms: int = _epoch_ms()
        self.allowed_tools = allowed_tools
        self.session_boot_id = session_boot_id
        self.workspace = workspace or Path.cwd()
        self.spawn_depth = spawn_depth
        self.fork_messages = fork_messages
        self.parent_cancel = parent_cancel
        self.mailbox = mailbox
        self.loop_runtime = loop_runtime
        self.cancel_token: asyncio.Event = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.input_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    def snapshot(self) -> SubAgentResult:
        duration_ms = max(0, _epoch_ms() - self.started_at_ms)
        return SubAgentResult(
            agent_id=self.id,
            agent_type=self.agent_type,
            assignment=self.assignment,
            model=self.model,
            nickname=self.nickname,
            status=self.status,
            result=self.result,
            steps_taken=self.steps_taken,
            duration_ms=duration_ms,
            from_prior_session=False,
            structured=self.structured_result,
        )


class SubAgentManager:
    """Manager for in-process sub-agents.

    Mirrors Rust ``SubAgentManager`` (mod.rs:726-). Runs agents as
    :class:`asyncio.Task` rather than multiprocessing subprocesses —
    LLM calls are IO-bound and Rust itself uses tokio::spawn.
    """

    def __init__(
        self,
        workspace: Path,
        max_agents: int = DEFAULT_MAX_AGENTS,
        state_path: Path | None = None,
        executor: SubAgentExecutor | None = None,
        mailbox: Mailbox | None = None,
        default_model: str = "deepseek-chat",
        llm_max_concurrent: int = 2,
    ) -> None:
        self.workspace = workspace
        self.max_agents = max_agents
        self.max_steps = DEFAULT_MAX_STEPS
        self.default_model = default_model
        self._state_path = state_path
        self._executor: SubAgentExecutor = executor or _stub_executor
        self._mailbox = mailbox
        # Gate concurrent sub-agent LLM streams: N parallel children plus
        # the parent all hitting one provider key is what triggers 429
        # rate-limit storms (and their multi-minute backoffs). Tool
        # execution is not gated — only the streaming call itself.
        self.llm_semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(llm_max_concurrent)
            if llm_max_concurrent > 0
            else None
        )
        self._agents: dict[str, SubAgent] = {}
        self._lock = asyncio.Lock()
        self._session_boot_id: str = f"boot_{uuid.uuid4().hex[:12]}"
        self._parent_cancel: asyncio.Event | None = None
        self._parent_completion_sink: Callable[[SubAgentCompletion], None] | None = (
            None
        )
        self._loop_runtime: SubAgentRuntime | None = None
        if state_path is not None:
            self._load_state()

    def attach_parent_completion_sink(
        self, sink: Callable[[SubAgentCompletion], None]
    ) -> None:
        """Wake the parent engine turn loop when a direct child finishes (#756)."""
        self._parent_completion_sink = sink

    def attach_loop_runtime(self, runtime: SubAgentRuntime) -> None:
        """Wire shared client/config for ``run_subagent_loop`` (Rust SubAgentRuntime)."""
        self._loop_runtime = runtime

    @property
    def loop_runtime(self) -> SubAgentRuntime | None:
        return self._loop_runtime

    @property
    def session_boot_id(self) -> str:
        return self._session_boot_id

    @property
    def mailbox(self) -> Mailbox | None:
        return self._mailbox

    def attach_parent_cancel(self, token: asyncio.Event) -> None:
        """Link parent engine cancellation to all descendant agents."""
        self._parent_cancel = token

    def running_count(self) -> int:
        return sum(
            1
            for a in self._agents.values()
            if a.status.kind is SubAgentStatusKind.RUNNING
        )

    def list_filtered(self, include_archived: bool = False) -> list[SubAgentResult]:
        out: list[SubAgentResult] = []
        for agent in self._agents.values():
            from_prior = self._is_from_prior_session(agent)
            if from_prior and not include_archived:
                continue
            snap = agent.snapshot()
            # Synthesize the from_prior_session flag manager-side.
            snap = SubAgentResult(
                agent_id=snap.agent_id,
                agent_type=snap.agent_type,
                assignment=snap.assignment,
                model=snap.model,
                nickname=snap.nickname,
                status=snap.status,
                result=snap.result,
                steps_taken=snap.steps_taken,
                duration_ms=snap.duration_ms,
                from_prior_session=from_prior,
            )
            out.append(snap)
        return out

    def list_agents(self) -> list[SubAgentResult]:
        return self.list_filtered(include_archived=False)

    def _loop_runtime_for_spawn(
        self, request: SpawnRequest, child_depth: int
    ) -> SubAgentRuntime | None:
        if self._loop_runtime is None:
            return None
        from dataclasses import replace

        rt = self._loop_runtime.with_spawn_depth(child_depth)
        if request.auto_approve is not None:
            rt = replace(rt, auto_approve=request.auto_approve)
        return rt

    async def spawn(self, request: SpawnRequest) -> SubAgentResult:
        async with self._lock:
            if self.running_count() >= self.max_agents:
                raise RuntimeError(
                    f"Too many sub-agents running ({self.max_agents} cap)"
                )
            child_depth = request.parent_depth + 1
            if child_depth > DEFAULT_MAX_SPAWN_DEPTH:
                raise RuntimeError(
                    f"max sub-agent spawn depth exceeded "
                    f"({DEFAULT_MAX_SPAWN_DEPTH}); refusing nested spawn at "
                    f"depth {child_depth}"
                )
            agent = SubAgent(
                agent_type=request.agent_type,
                prompt=request.prompt,
                assignment=request.assignment,
                model=request.model or self.default_model,
                nickname=request.nickname
                or whale_nickname_for_index(len(self._agents)),
                allowed_tools=request.allowed_tools,
                session_boot_id=self._session_boot_id,
                workspace=self.workspace,
                spawn_depth=child_depth,
                fork_messages=request.fork_messages if request.fork_context else None,
                parent_cancel=self._parent_cancel,
                mailbox=self._mailbox,
                loop_runtime=self._loop_runtime_for_spawn(request, child_depth),
                output_schema=request.output_schema,
            )
            self._agents[agent.id] = agent
            snapshot = agent.snapshot()
            self._persist_best_effort()

        if self._mailbox is not None:
            self._mailbox.send(
                MailboxMessage.started(agent.id, request.agent_type.value)
            )
        agent.task = asyncio.create_task(self._drive_agent(agent))
        return snapshot

    async def get_result(self, agent_id: str) -> SubAgentResult:
        async with self._lock:
            agent = self._require_agent(agent_id)
            return agent.snapshot()

    async def cancel(self, agent_id: str) -> SubAgentResult:
        task: asyncio.Task[None] | None = None
        async with self._lock:
            agent = self._require_agent(agent_id)
            agent.cancel_token.set()
            task = agent.task
            if agent.status.kind is SubAgentStatusKind.RUNNING:
                agent.status = SubAgentStatus.cancelled()
            self._persist_best_effort()
            snapshot = agent.snapshot()

        if self._mailbox is not None:
            self._mailbox.send(MailboxMessage.cancelled(agent_id))
        if task is not None and not task.done():
            task.cancel()
        return snapshot

    async def send_input(
        self, agent_id: str, text: str, interrupt: bool = False
    ) -> None:
        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent.status.kind is not SubAgentStatusKind.RUNNING:
                raise RuntimeError(
                    f"Cannot send input to {agent_id}: {agent.status.kind.value}"
                )
        await agent.input_queue.put((text, interrupt))

    async def assign(
        self,
        agent_id: str,
        objective: str | None = None,
        role: str | None = None,
        message: str | None = None,
        interrupt: bool = False,
    ) -> SubAgentResult:
        async with self._lock:
            agent = self._require_agent(agent_id)
            if objective is not None:
                agent.assignment = SubAgentAssignment(
                    objective=objective, role=role or agent.assignment.role
                )
            elif role is not None:
                agent.assignment = SubAgentAssignment(
                    objective=agent.assignment.objective, role=role
                )
            snapshot = agent.snapshot()
        if message is not None:
            await self.send_input(agent_id, message, interrupt=interrupt)
        return snapshot

    async def resume(self, agent_id: str) -> SubAgentResult:
        """Re-open a terminated agent for a new prompt.

        Mirrors Rust ``SubAgentManager::resume`` — resurrects the status
        back to Running and re-spawns the driver task.
        """
        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent.status.kind is SubAgentStatusKind.RUNNING:
                raise RuntimeError(f"Agent {agent_id} is already running")
            agent.status = SubAgentStatus.running()
            agent.result = None
            agent.cancel_token = asyncio.Event()
            agent.started_at_ms = _epoch_ms()
            self._persist_best_effort()
            snapshot = agent.snapshot()

        if self._mailbox is not None:
            self._mailbox.send(
                MailboxMessage.started(agent_id, agent.agent_type.value)
            )
        agent.task = asyncio.create_task(self._drive_agent(agent))
        return snapshot

    async def close(self, agent_id: str) -> SubAgentResult:
        """Terminate and remove an agent from the active map."""
        snapshot = await self.cancel(agent_id)
        async with self._lock:
            self._agents.pop(agent_id, None)
            self._persist_best_effort()
        return snapshot

    async def wait(
        self, agent_ids: list[str], mode: str, timeout_ms: int
    ) -> list[SubAgentResult]:
        """Wait until `mode` ("any" or "all") targets are terminal.

        Returns the snapshots after the wait concludes (either mode
        satisfied or timeout expired).
        """
        if mode not in ("any", "all", "first"):
            raise ValueError(f"Unknown wait mode: {mode}")
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            async with self._lock:
                snapshots = [
                    self._require_agent(aid).snapshot() for aid in agent_ids
                ]
            terminals = [s for s in snapshots if s.status.kind is not SubAgentStatusKind.RUNNING]
            if mode in ("any", "first"):
                if terminals:
                    return snapshots
            else:  # all
                if len(terminals) == len(snapshots):
                    return snapshots
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return snapshots
            await asyncio.sleep(min(0.05, remaining))

    def known_agent_ids(self) -> set[str]:
        """Snapshot the ids of every agent currently tracked.

        Used by a turn's monitor at start-up to tag pre-existing agents as
        *foreign*: turns are serial per thread, so any agent already present
        when a turn begins was spawned by an earlier turn and must not have
        its mailbox events re-attributed to the new turn.
        """
        return set(self._agents)

    async def shutdown(self) -> None:
        """Cancel and join every running agent."""
        async with self._lock:
            agents = list(self._agents.values())
        for agent in agents:
            agent.cancel_token.set()
        for agent in agents:
            if agent.task is not None and not agent.task.done():
                agent.task.cancel()
                try:
                    await agent.task
                except (asyncio.CancelledError, BaseException):  # noqa: BLE001
                    pass

    # --- internal ------------------------------------------------------

    def _require_agent(self, agent_id: str) -> SubAgent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Unknown agent: {agent_id}")
        return agent

    def _is_from_prior_session(self, agent: SubAgent) -> bool:
        return (
            not agent.session_boot_id
            or agent.session_boot_id != self._session_boot_id
        )

    def _notify_parent_completion(self, agent: SubAgent) -> None:
        """Wake the parent turn loop (#756) for direct children in any terminal state."""
        if agent.spawn_depth != 1 or self._parent_completion_sink is None:
            return
        snap = agent.snapshot()
        payload = build_completion_payload(snap)
        try:
            self._parent_completion_sink(
                SubAgentCompletion(agent_id=agent.id, payload=payload)
            )
        except Exception:  # noqa: BLE001
            pass

    async def _drive_agent(self, agent: SubAgent) -> None:
        logger.info("subagent_drive_start id=%s type=%s depth=%d", agent.id, agent.agent_type.value, agent.spawn_depth)
        if self._parent_cancel is not None and self._parent_cancel.is_set():
            agent.cancel_token.set()
        try:
            result = await self._executor(agent, agent.cancel_token)
        except asyncio.CancelledError:
            logger.info("subagent_drive_cancelled id=%s", agent.id)
            async with self._lock:
                if agent.status.kind is SubAgentStatusKind.RUNNING:
                    agent.status = SubAgentStatus.cancelled()
                self._persist_best_effort()
            if self._mailbox is not None:
                self._mailbox.send(MailboxMessage.cancelled(agent.id))
            self._notify_parent_completion(agent)
            return
        except Exception as exc:  # noqa: BLE001 — translate to Failed status
            logger.error("subagent_drive_failed id=%s error=%s", agent.id, exc)
            async with self._lock:
                agent.status = SubAgentStatus.failed(str(exc))
                self._persist_best_effort()
            if self._mailbox is not None:
                self._mailbox.send(MailboxMessage.failed(agent.id, str(exc)))
            self._notify_parent_completion(agent)
            return

        async with self._lock:
            if agent.cancel_token.is_set():
                if agent.status.kind is SubAgentStatusKind.RUNNING:
                    agent.status = SubAgentStatus.cancelled()
            else:
                agent.status = SubAgentStatus.completed()
                if isinstance(result, AgentRunOutput):
                    agent.result = result.text
                    agent.structured_result = result.structured
                else:
                    agent.result = str(result) if result is not None else None
                    agent.structured_result = None
            self._persist_best_effort()

        logger.info(
            "subagent_drive_done id=%s status=%s steps=%d",
            agent.id, agent.status.kind.value, agent.steps_taken,
        )
        if self._mailbox is not None:
            if agent.status.kind is SubAgentStatusKind.CANCELLED:
                self._mailbox.send(MailboxMessage.cancelled(agent.id))
            else:
                summary = (agent.result or "")[:_MAX_CARD_RESULT_CHARS] if agent.result else ""
                self._mailbox.send(MailboxMessage.completed(agent.id, summary))

        self._notify_parent_completion(agent)
        await self._evict_terminal_agents()

    async def _evict_terminal_agents(self) -> None:
        async with self._lock:
            terminal = [
                (aid, a) for aid, a in self._agents.items()
                if a.status.kind is not SubAgentStatusKind.RUNNING
            ]
            if len(terminal) <= _MAX_TERMINAL_AGENTS_IN_MEMORY:
                return
            terminal.sort(key=lambda x: x[1].started_at_ms or 0)
            to_remove = len(terminal) - _MAX_TERMINAL_AGENTS_IN_MEMORY
            for aid, _ in terminal[:to_remove]:
                del self._agents[aid]
            self._persist_best_effort()

    def _persist_best_effort(self) -> None:
        if self._state_path is None:
            return
        try:
            self._persist_state()
        except Exception as exc:  # noqa: BLE001
            # Match Rust's eprintln! best-effort behavior.
            print(f"Failed to persist sub-agent state: {exc}")

    def _persist_state(self) -> None:
        if self._state_path is None:
            return
        now_ms = _epoch_ms()
        agents_payload = []
        for agent in sorted(self._agents.values(), key=lambda a: a.id):
            agents_payload.append(
                {
                    "id": agent.id,
                    "agent_type": agent.agent_type.value,
                    "prompt": agent.prompt,
                    "assignment": {
                        "objective": agent.assignment.objective,
                        "role": agent.assignment.role,
                    },
                    "model": agent.model,
                    "nickname": agent.nickname,
                    "status": agent.status.to_dict(),
                    "result": agent.result,
                    "steps_taken": agent.steps_taken,
                    "duration_ms": max(0, now_ms - agent.started_at_ms),
                    "allowed_tools": agent.allowed_tools or [],
                    "updated_at_ms": now_ms,
                    "session_boot_id": agent.session_boot_id,
                    "spawn_depth": agent.spawn_depth,
                }
            )
        payload = {
            "schema_version": SUBAGENT_STATE_SCHEMA_VERSION,
            "agents": agents_payload,
        }
        _write_json_atomic(self._state_path, payload)

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        data = json.loads(self._state_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SUBAGENT_STATE_SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported sub-agent state schema {data.get('schema_version')}"
            )
        self._agents.clear()
        for raw in data.get("agents", []):
            agent = SubAgent(
                agent_type=SubAgentType(raw["agent_type"]),
                prompt=raw["prompt"],
                assignment=SubAgentAssignment(
                    objective=raw["assignment"]["objective"],
                    role=raw["assignment"].get("role"),
                ),
                model=raw.get("model", self.default_model),
                nickname=raw.get("nickname"),
                allowed_tools=raw.get("allowed_tools") or None,
                session_boot_id=raw.get("session_boot_id", ""),
                workspace=self.workspace,
                spawn_depth=int(raw.get("spawn_depth", 0) or 0),
            )
            # Restore id from persisted record, overwriting the freshly
            # generated one.
            agent.id = raw["id"]
            # Running on disk → Interrupted on load (Rust parity).
            status = SubAgentStatus.from_dict(raw["status"])
            if status.kind is SubAgentStatusKind.RUNNING:
                status = SubAgentStatus.interrupted(SUBAGENT_RESTART_REASON)
            agent.status = status
            agent.result = raw.get("result")
            agent.steps_taken = raw.get("steps_taken", 0)
            duration_ms = raw.get("duration_ms", 0)
            agent.started_at_ms = _epoch_ms() - max(0, int(duration_ms))
            self._agents[agent.id] = agent


@dataclass(slots=True)
class SubAgentRuntime:
    """Runtime context forwarded to children on spawn.

    Rust analogue: ``SubAgentRuntime`` (mod.rs:587). All depths share
    :attr:`manager`; children increment :attr:`spawn_depth` only.
    """

    manager: SubAgentManager
    client: Any
    model: str
    config: Config
    workspace: Path
    allow_shell: bool = True
    # Secure default: children do NOT auto-approve unless the parent session
    # explicitly opts in (mirrors the task system's GHSA default). The engine
    # always passes the resolved value from ``approval_handler``.
    auto_approve: bool = False
    task_manager: Any = None
    cancel_token: asyncio.Event = field(default_factory=asyncio.Event)
    mailbox: Mailbox | None = None
    spawn_depth: int = 0
    max_spawn_depth: int = DEFAULT_MAX_SPAWN_DEPTH

    def would_exceed_depth(self) -> bool:
        return self.spawn_depth + 1 > self.max_spawn_depth

    def with_spawn_depth(self, depth: int) -> SubAgentRuntime:
        return SubAgentRuntime(
            manager=self.manager,
            client=self.client,
            model=self.model,
            config=self.config,
            workspace=self.workspace,
            allow_shell=self.allow_shell,
            auto_approve=self.auto_approve,
            task_manager=self.task_manager,
            cancel_token=self.cancel_token,
            mailbox=self.mailbox,
            spawn_depth=depth,
            max_spawn_depth=self.max_spawn_depth,
        )

    def child(self) -> SubAgentRuntime:
        return SubAgentRuntime(
            manager=self.manager,
            client=self.client,
            model=self.model,
            config=self.config,
            workspace=self.workspace,
            allow_shell=self.allow_shell,
            auto_approve=self.auto_approve,
            task_manager=self.task_manager,
            cancel_token=self.cancel_token,
            mailbox=self.mailbox,
            spawn_depth=self.spawn_depth + 1,
            max_spawn_depth=self.max_spawn_depth,
        )


        raise


# --- sub-agent LLM loop (mirrors Rust ``run_subagent``) --------------------


def _subagent_cancelled(
    cancel: asyncio.Event,
    agent: SubAgent,
) -> bool:
    if cancel.is_set() or agent.cancel_token.is_set():
        return True
    return agent.parent_cancel is not None and agent.parent_cancel.is_set()


def _reject_subagent_interactive_shell(tool_name: str, input_data: dict[str, Any]) -> None:
    if tool_name != "exec_shell":
        return
    if input_data.get("interactive") is True:
        raise RuntimeError(
            "Sub-agents cannot use exec_shell with interactive=true "
            "(would take over the parent TUI terminal)"
        )


async def _execute_subagent_tool(
    registry: object,
    context: object,
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    auto_approve: bool,
) -> str:
    from deepseek_tui.tools.registry import ApprovalRequirement, ToolError
    from deepseek_tui.tools.registry import ToolRegistry

    assert isinstance(registry, ToolRegistry)
    _reject_subagent_interactive_shell(tool_name, tool_input)
    tool = registry.get(tool_name)
    if not auto_approve and tool.approval_requirement() != ApprovalRequirement.AUTO:
        return (
            f"Error: Tool {tool_name} requires approval and cannot run "
            "inside this sub-agent unless the parent session is auto-approved"
        )
    try:
        result = await registry.execute(tool_name, tool_input, context)  # type: ignore[arg-type]
        if not result.success:
            return f"Error: {result.content}"
        return result.content
    except ToolError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def _structured_output_contract() -> str:
    return (
        "Final output contract:\n"
        "- Your final action MUST be a structured_output tool call.\n"
        "- The structured_output arguments are the return value of this subagent.\n"
        "- Do not emit a prose final answer instead of structured_output.\n"
        "- If you need to inspect files or run commands first, do so, then call "
        "structured_output exactly once."
    )


_SUBAGENT_FINAL_REPORT_NUDGE = (
    "You have gathered enough information. Stop exploring and do NOT call any "
    "more tools. Write your final report now as your message: summarize your "
    "findings, conclusions, and any recommendations in full prose."
)


def _assistant_text_and_thinking(message: Any | None) -> tuple[str, str]:
    """Split an assistant message into its visible text and reasoning text.

    Reasoning models (DeepSeek V4/R1) routinely emit their final answer in the
    thinking channel with an empty text block on the terminal round. Harvesting
    only text blocks then completes the sub-agent with an empty result, so the
    caller falls back to reasoning to guarantee a usable deliverable.
    """
    from deepseek_tui.protocol.messages import TextBlock, ThinkingBlock

    if message is None:
        return "", ""
    text_parts: list[str] = []
    think_parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ThinkingBlock):
            if block.thinking.strip():
                think_parts.append(block.thinking)
    thinking = "\n".join(think_parts).strip()
    # Drop "(reasoning omitted)" placeholder lines so they never surface as a
    # sub-agent's result (mirrors the renderer's sanitizeReasoningPlaceholders).
    if thinking:
        thinking = "\n".join(
            line
            for line in thinking.splitlines()
            if line.strip().lower() != "(reasoning omitted)"
        ).strip()
    return "".join(text_parts).strip(), thinking


async def run_subagent_loop(
    agent: SubAgent,
    runtime: SubAgentRuntime,
    cancel: asyncio.Event,
) -> AgentRunOutput:
    """Drive one sub-agent to completion without nesting a full Engine."""
    from deepseek_tui.engine.turn import TurnLoop
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.messages import MessageRequest
    from deepseek_tui.tools.registry import build_subagent_registry
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.validation import (
        STRUCTURED_OUTPUT_TOOL_NAME,
        StructuredOutputTool,
    )

    system_prompt = build_subagent_system_prompt(agent.agent_type, agent.assignment)
    extra_tools = []
    if agent.output_schema:
        extra_tools.append(StructuredOutputTool(agent.output_schema))
        system_prompt = f"{system_prompt}\n\n{_structured_output_contract()}"
    registry = build_subagent_registry(
        runtime.config,
        allowed_tools=agent.allowed_tools,
        client=runtime.client,
        root_model=agent.model,
        extra_tools=extra_tools or None,
    )
    context = ToolContext(
        working_directory=agent.workspace,
        trust_mode=False,
        task_manager=runtime.task_manager,
        subagent_manager=runtime.manager,
        metadata={
            "subagent_depth": agent.spawn_depth,
            "subagent_runtime": runtime,
            "auto_approve": runtime.auto_approve,
        },
    )
    from deepseek_tui.policy.sandbox import sandbox_policy_for_mode

    context.execution_sandbox_policy = sandbox_policy_for_mode(
        "agent",
        agent.workspace,
    )
    registry.set_context(context)
    api_tools = registry.to_api_tools()

    messages: list[Message] = []
    if agent.fork_messages:
        messages.extend(_messages_from_fork_dicts(agent.fork_messages))
    messages.append(Message.user(agent.prompt))

    turn_loop = TurnLoop(runtime.client)
    final_text = ""
    last_thinking = ""
    structured_value: Any | None = None
    steps = 0
    last_usage: object | None = None
    force_summary = False

    async def _noop_emit(_event: object) -> None:
        return None

    for _ in range(DEFAULT_MAX_STEPS):
        if _subagent_cancelled(cancel, agent):
            raise asyncio.CancelledError

        steps += 1
        agent.steps_taken = steps

        # On a forced-summary round we strip tools so the model has no choice
        # but to emit its final report as text.
        round_tools = [] if force_summary else api_tools
        request = MessageRequest(
            model=agent.model,
            messages=messages,
            system_prompt=system_prompt,
            tools=round_tools,
            tool_choice={"type": "auto"} if round_tools else None,
            max_tokens=4096,
            stream=True,
        )
        llm_gate = getattr(runtime.manager, "llm_semaphore", None)
        if llm_gate is not None:
            async with llm_gate:
                result = await turn_loop.run(
                    request,
                    _noop_emit,
                    cancel,
                    tools=round_tools,
                )
        else:
            result = await turn_loop.run(
                request,
                _noop_emit,
                cancel,
                tools=round_tools,
            )

        if result.usage is not None:
            last_usage = result.usage

        if result.cancelled:
            raise asyncio.CancelledError

        if result.assistant_message is not None:
            messages.append(result.assistant_message)

        round_text, round_thinking = _assistant_text_and_thinking(
            result.assistant_message
        )
        if round_text:
            final_text = round_text
        if round_thinking:
            last_thinking = round_thinking

        if not result.tool_calls:
            if round_text:
                # Genuine prose final answer.
                break
            # No text and no tool calls: the model stalled on a reasoning-only
            # round (e.g. "let me also look at ..." with nothing actionable).
            # Nudge it once, tools off, to produce a real report before we fall
            # back to surfacing raw reasoning as the deliverable.
            if not force_summary and structured_value is None:
                force_summary = True
                messages.append(Message.user(_SUBAGENT_FINAL_REPORT_NUDGE))
                continue
            if round_thinking:
                final_text = round_thinking
            break

        from deepseek_tui.protocol.messages import ToolUseBlock

        messages.append(
            Message.assistant_with_tools(
                [
                    ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments)
                    for tc in result.tool_calls
                ]
            )
        )

        for tc in result.tool_calls:
            if runtime.mailbox is not None:
                runtime.mailbox.send(
                    MailboxMessage.tool_call_started(agent.id, tc.name, steps)
                )
            if tc.name == STRUCTURED_OUTPUT_TOOL_NAME:
                tool_result = await registry.execute(tc.name, tc.arguments, context)
                output = (
                    tool_result.content
                    if tool_result.success
                    else f"Error: {tool_result.content}"
                )
                ok = tool_result.success
                if ok and tool_result.metadata.get("terminate_subagent"):
                    structured_value = tool_result.metadata.get("value")
            else:
                output = await _execute_subagent_tool(
                    registry,
                    context,
                    tool_name=tc.name,
                    tool_input=tc.arguments,
                    auto_approve=runtime.auto_approve,
                )
                ok = not output.startswith("Error:")
            if runtime.mailbox is not None:
                runtime.mailbox.send(
                    MailboxMessage.tool_call_completed(
                        agent.id, tc.name, steps, ok
                    )
                )
            messages.append(Message.tool_result(tc.id, output, is_error=not ok))
            if structured_value is not None:
                break
        if structured_value is not None:
            break

    if runtime.mailbox is not None and last_usage is not None:
        runtime.mailbox.send(
            MailboxMessage.token_usage(
                agent.id,
                agent.model,
                {
                    "input_tokens": getattr(last_usage, "input_tokens", 0),
                    "output_tokens": getattr(last_usage, "output_tokens", 0),
                    "reasoning_tokens": getattr(last_usage, "reasoning_tokens", 0),
                },
            )
        )

    agent.steps_taken = steps
    if agent.output_schema and structured_value is None:
        raise RuntimeError("sub-agent did not return structured_output")
    # Last-resort fallback: a sub-agent that ran out of steps (or whose terminal
    # text was empty) still owes the parent *something* to read back.
    if not final_text and last_thinking:
        final_text = last_thinking
    return AgentRunOutput(text=final_text, structured=structured_value)


def _messages_from_fork_dicts(raw_messages: list[dict[str, Any]]) -> list[Message]:
    from deepseek_tui.protocol.messages import Message

    out: list[Message] = []
    for item in raw_messages:
        try:
            out.append(Message.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return out


# --- helpers ----------------------------------------------------------------


def _epoch_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Sub-agent mailbox — structured progress/lifecycle event stream.
#
# Mirrors `crates/tui/src/tools/subagent/mailbox.rs` (478 lines).
#
# The mailbox carries lifecycle events from a tree of sub-agents to
# interested consumers (parent agent, UI card, persistence). Sequence
# numbers are monotonic across the whole mailbox so consumers see a single
# consistent ordering even with multiple producers.
#
import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any


class MailboxMessageKind(str, Enum):
    STARTED = "started"
    PROGRESS = "progress"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    CHILD_SPAWNED = "child_spawned"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TOKEN_USAGE = "token_usage"


@dataclass(slots=True, frozen=True)
class MailboxMessage:
    """Structured progress envelope.

    Tagged union keyed by :attr:`kind`. Only the fields relevant to the
    kind are populated; other fields are ``None``.
    """

    kind: MailboxMessageKind
    agent_id: str
    agent_type: str | None = None
    status: str | None = None
    tool_name: str | None = None
    step: int | None = None
    ok: bool | None = None
    parent_id: str | None = None
    summary: str | None = None
    error: str | None = None
    model: str | None = None
    usage: dict[str, Any] | None = None

    @staticmethod
    def started(agent_id: str, agent_type: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.STARTED,
            agent_id=agent_id,
            agent_type=agent_type,
        )

    @staticmethod
    def progress(agent_id: str, status: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.PROGRESS, agent_id=agent_id, status=status
        )

    @staticmethod
    def tool_call_started(agent_id: str, tool_name: str, step: int) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.TOOL_CALL_STARTED,
            agent_id=agent_id,
            tool_name=tool_name,
            step=step,
        )

    @staticmethod
    def tool_call_completed(
        agent_id: str, tool_name: str, step: int, ok: bool
    ) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.TOOL_CALL_COMPLETED,
            agent_id=agent_id,
            tool_name=tool_name,
            step=step,
            ok=ok,
        )

    @staticmethod
    def child_spawned(parent_id: str, child_id: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.CHILD_SPAWNED,
            agent_id=child_id,
            parent_id=parent_id,
        )

    @staticmethod
    def completed(agent_id: str, summary: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.COMPLETED, agent_id=agent_id, summary=summary
        )

    @staticmethod
    def failed(agent_id: str, error: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.FAILED, agent_id=agent_id, error=error
        )

    @staticmethod
    def cancelled(agent_id: str) -> MailboxMessage:
        return MailboxMessage(kind=MailboxMessageKind.CANCELLED, agent_id=agent_id)

    @staticmethod
    def token_usage(
        agent_id: str, model: str, usage: dict[str, Any]
    ) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.TOKEN_USAGE,
            agent_id=agent_id,
            model=model,
            usage=usage,
        )


@dataclass(slots=True, frozen=True)
class MailboxEnvelope:
    seq: int
    message: MailboxMessage


MAILBOX_MAX_ENVELOPES = 512


class Mailbox:
    """Sender side of the mailbox. Cheaply sharable via ``share()``.

    Mirrors Rust ``Mailbox`` (mailbox.rs:135-). In Rust this is ``Clone``
    through an ``Arc``; here we expose ``share()`` which returns the same
    underlying object so child runtimes observing the same stream stay
    in sync.
    """

    def __init__(self, cancel_token: asyncio.Event | None = None) -> None:
        self._queue: asyncio.Queue[MailboxEnvelope] = asyncio.Queue(
            maxsize=MAILBOX_MAX_ENVELOPES
        )
        self._seq = 0
        self._closed = False
        self._cancel_token = cancel_token or asyncio.Event()

    @property
    def cancel_token(self) -> asyncio.Event:
        return self._cancel_token

    def share(self) -> Mailbox:
        """Return this mailbox so child producers publish into the same stream."""
        return self

    def is_closed(self) -> bool:
        return self._closed

    def send(self, message: MailboxMessage) -> bool:
        """Enqueue a message with a fresh monotonic seq.

        Returns False if the mailbox is already closed.
        """
        if self._closed:
            return False
        self._seq += 1
        envelope = MailboxEnvelope(seq=self._seq, message=message)
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull:
            # Drop oldest progress so lifecycle events can still land.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(envelope)
            except asyncio.QueueEmpty:
                return False
        return True

    def close(self) -> None:
        """Close the mailbox and cancel the bound token.

        Per Rust behavior: closing signals cancellation through the shared
        token so children cooperating on the same token shut down too.
        """
        if self._closed:
            return
        self._closed = True
        self._cancel_token.set()

    async def recv(self) -> MailboxEnvelope | None:
        """Receive next envelope. Returns None if closed and queue drained."""
        if self._closed and self._queue.empty():
            return None
        try:
            return await self._queue.get()
        except asyncio.CancelledError:
            return None

    def try_recv(self) -> MailboxEnvelope | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def drain_available(self) -> list[MailboxEnvelope]:
        """Non-blocking drain of everything already enqueued."""
        out: list[MailboxEnvelope] = []
        while True:
            envelope = self.try_recv()
            if envelope is None:
                return out
            out.append(envelope)


# Sub-agent completion payloads for parent turn handoff (Rust issue #756).
import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubAgentCompletion:
    """Notification that a direct child sub-agent finished."""

    agent_id: str
    payload: str


def summarize_subagent_result(snap: SubAgentResult) -> str:
    """One-line human summary for the parent sidebar / transcript."""

    if snap.status.kind is SubAgentStatusKind.FAILED:
        return f"Failed: {snap.status.message or 'unknown error'}"
    if snap.status.kind is SubAgentStatusKind.CANCELLED:
        return "Cancelled"
    if snap.status.kind is SubAgentStatusKind.INTERRUPTED:
        return f"Interrupted: {snap.status.message or 'unknown'}"
    body = (snap.result or "").strip()
    if not body:
        return f"Completed ({snap.agent_type.value})"
    first = body.splitlines()[0].strip()
    if len(first) > 240:
        return first[:237] + "..."
    return first


def subagent_done_sentinel(snap: SubAgentResult) -> str:
    """Build ``<deepseek:subagent.done>`` JSON sentinel."""

    if snap.status.kind is SubAgentStatusKind.FAILED:
        payload = json.dumps(
            {
                "agent_id": snap.agent_id,
                "status": "failed",
                "error": snap.status.message or "unknown",
            },
            ensure_ascii=False,
        )
    else:
        payload = json.dumps(
            {
                "agent_id": snap.agent_id,
                "agent_type": snap.agent_type.value,
                "status": snap.status.kind.value,
                "duration_ms": snap.duration_ms,
                "steps": snap.steps_taken,
                "summary": summarize_subagent_result(snap),
            },
            ensure_ascii=False,
        )
    return f"<deepseek:subagent.done>{payload}</deepseek:subagent.done>"


_MAX_PAYLOAD_CHARS = 8_000


def build_completion_payload(snap: SubAgentResult) -> str:
    """Human summary on line 1, sentinel on line 2 (Rust ``run_subagent_task``)."""
    summary = summarize_subagent_result(snap)
    sentinel = subagent_done_sentinel(snap)
    payload = f"{summary}\n{sentinel}"
    if len(payload) > _MAX_PAYLOAD_CHARS:
        payload = payload[:_MAX_PAYLOAD_CHARS] + "\n…[truncated]"
    return payload


# Sub-agent run result types (workflow + structured output).
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AgentRunOutput:
    """Result of one sub-agent loop execution."""

    text: str
    structured: dict[str, Any] | list[Any] | None = None
