"""Tool dispatch — plan/execute helpers for the per-turn tool batch.

Mirrors `crates/tui/src/core/engine/dispatch.rs:1-354`.

Owns:
  * The ``multi_tool_use.parallel`` payload parser.
  * Policy predicates: parallel batch, plan-mode stop/force, MCP safety.
  * Tool execution plan/outcome types.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.tools.base import ToolError, ToolResult

# --- Types (Rust dispatch.rs:28-65) --------------------------------------


@dataclass
class ToolExecutionPlan:
    """Per-tool execution plan built before dispatch."""

    index: int
    id: str
    name: str
    input: dict[str, Any]
    caller: str | None = None
    interactive: bool = False
    approval_required: bool = False
    approval_description: str = "Tool execution requires approval"
    supports_parallel: bool = False
    read_only: bool = False
    blocked_error: ToolError | None = None


@dataclass
class ToolExecOutcome:
    """Result from executing a single tool."""

    index: int
    id: str
    name: str
    input: dict[str, Any]
    started_at: float = field(default_factory=time.monotonic)
    result: ToolResult | None = None
    error: ToolError | None = None


@dataclass
class ParallelToolResultEntry:
    tool_name: str
    success: bool
    content: str
    error: str | None = None


@dataclass
class ParallelToolResult:
    results: list[ParallelToolResultEntry] = field(default_factory=list)


# --- Caller policy (Rust dispatch.rs:76-94) -------------------------------


def caller_type_for_tool_use(caller: str | None) -> str:
    return caller or "direct"


def caller_allowed_for_tool(
    caller: str | None,
    allowed_callers: list[str] | None,
) -> bool:
    """Check if caller type is allowed for a tool definition."""
    requested = caller_type_for_tool_use(caller)
    if allowed_callers is None:
        return requested == "direct"
    if not allowed_callers:
        return requested == "direct"
    return requested in allowed_callers


# --- Error formatting (Rust dispatch.rs:96-126) ---------------------------


def format_tool_error(err: Exception, tool_name: str) -> str:
    """Format a tool error into a human-friendly message."""
    msg = str(err)
    lower = msg.lower()
    if "invalid input" in lower:
        return f"Invalid input for tool '{tool_name}': {msg}"
    if "missing" in lower and "field" in lower:
        return f"Tool '{tool_name}' is missing a required field: {msg}"
    if "path escape" in lower or "workspace" in lower:
        return (
            f"Path escapes workspace: {msg}. "
            "Use a workspace-relative path or enable trust mode."
        )
    if "timeout" in lower:
        return f"Tool '{tool_name}' timed out: {msg}"
    if "not available" in lower:
        if "current tool catalog" in lower or "did you mean" in lower:
            return msg
        return (
            f"Tool '{tool_name}' is not available: {msg}. "
            "Check mode, feature flags, or tool name."
        )
    if "permission" in lower or "denied" in lower:
        return (
            f"Tool '{tool_name}' was denied: {msg}. "
            "Adjust approval mode or request permission."
        )
    return msg


# --- Parallel tool calls (Rust dispatch.rs:215-259) -----------------------


def _normalize_parallel_tool_name(raw: str) -> str:
    name = raw.strip()
    for prefix in ("functions.", "tools.", "tool."):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def parse_parallel_tool_calls(
    input_data: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Parse a multi_tool_use.parallel payload into (name, params) pairs."""
    tool_uses = input_data.get("tool_uses")
    if not isinstance(tool_uses, list) or not tool_uses:
        raise ToolError(
            "multi_tool_use.parallel requires at least one tool call in 'tool_uses'"
        )

    calls: list[tuple[str, dict[str, Any]]] = []
    for item in tool_uses:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("recipient_name")
            or item.get("tool_name")
            or item.get("name")
            or item.get("tool")
        )
        if not isinstance(name, str):
            raise ToolError("Each tool_use must have a 'recipient_name' or 'name'")
        params = (
            item.get("parameters")
            or item.get("input")
            or item.get("args")
            or item.get("arguments")
            or {}
        )
        if not isinstance(params, dict):
            params = {}
        calls.append((_normalize_parallel_tool_name(name), params))

    return calls


# --- Dispatch policy (Rust dispatch.rs:263-355) ---------------------------


def should_parallelize_tool_batch(plans: list[ToolExecutionPlan]) -> bool:
    """True if all tools in the batch are safe for parallel execution."""
    if not plans:
        return False
    return all(
        p.read_only and p.supports_parallel and not p.approval_required and not p.interactive
        for p in plans
    )


def should_stop_after_plan_tool(
    mode: str, tool_name: str, success: bool
) -> bool:
    """In Plan mode, stop after a successful update_plan."""
    return mode == "plan" and tool_name == "update_plan" and success


def should_force_update_plan_first(mode: str, content: str) -> bool:
    """In Plan mode, detect quick-plan requests that skip repo exploration."""
    if mode != "plan":
        return False

    lower = content.lower()
    plan_needles = (
        "quick plan", "short plan", "simple plan",
        "3-step plan", "3 step plan", "three-step plan", "three step plan",
        "high-level plan", "high level plan",
        "give me a plan", "make a plan", "outline a plan", "draft a plan",
    )
    if not any(n in lower for n in plan_needles):
        return False

    exploration_needles = (
        "inspect the repo", "inspect the code", "explore the repo",
        "search the repo", "read the code", "review the code",
        "analyze the code", "investigate", "look through",
        "understand the current", "ground it in the codebase",
        "based on the codebase",
    )
    return not any(n in lower for n in exploration_needles)


# --- MCP tool policy (Rust dispatch.rs:326-355) ---------------------------

_MCP_PARALLEL_SAFE = frozenset(
    {
        "list_mcp_resources",
        "list_mcp_resource_templates",
        "mcp_read_resource",
        "read_mcp_resource",
        "mcp_get_prompt",
    }
)


def mcp_tool_is_parallel_safe(name: str) -> bool:
    return name in _MCP_PARALLEL_SAFE


def mcp_tool_is_read_only(name: str) -> bool:
    return name in _MCP_PARALLEL_SAFE


def mcp_tool_approval_description(name: str) -> str:
    if mcp_tool_is_read_only(name):
        return f"Read-only MCP tool '{name}'"
    return f"MCP tool '{name}' may have side effects"
