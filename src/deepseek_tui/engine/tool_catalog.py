"""Deferred tool catalog and built-in advanced tool helpers.

Mirrors `crates/tui/src/core/engine/tool_catalog.rs:1-475`.

The streaming turn loop owns when tools are offered or executed. This module
owns the catalog-level policy around deferred loading, tool search, missing
tool suggestions, and the small set of built-in advanced tools that are not
registered by the normal tool registry.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from deepseek_tui.tools.base import ToolError, ToolResult

# --- Constants (Rust tool_catalog.rs:18-26) -------------------------------

MULTI_TOOL_PARALLEL_NAME = "multi_tool_use.parallel"
REQUEST_USER_INPUT_NAME = "request_user_input"
CODE_EXECUTION_TOOL_NAME = "code_execution"

TOOL_SEARCH_REGEX_NAME = "tool_search_tool_regex"
TOOL_SEARCH_BM25_NAME = "tool_search_tool_bm25"

# --- Tool search predicate ------------------------------------------------


def is_tool_search_tool(name: str) -> bool:
    return name in (TOOL_SEARCH_REGEX_NAME, TOOL_SEARCH_BM25_NAME)


# --- Deferred loading policy (Rust tool_catalog.rs:31-99) -----------------

_ALWAYS_ACTIVE_TOOLS = frozenset(
    {
        "read_file",
        "list_dir",
        "grep_files",
        "file_search",
        "diagnostics",
        "rlm",
        "recall_archive",
        MULTI_TOOL_PARALLEL_NAME,
        "update_plan",
        "checklist_write",
        "todo_write",
        "task_create",
        "task_list",
        "task_read",
        "task_gate_run",
        "task_shell_start",
        "task_shell_wait",
        # Sub-agent orchestration — keep visible alongside task_* so the
        # model does not reach for task_create when the user asks for
        # agent_spawn (both families were deferred in Rust; task_* was
        # promoted to always-active in Python and created a selection bias).
        "agent_spawn",
        "agent_result",
        "agent_wait",
        "agent_list",
        "agent_cancel",
        "delegate_to_agent",
        "github_issue_context",
        "github_pr_context",
        REQUEST_USER_INPUT_NAME,
    }
)

_SHELL_TOOLS = frozenset(
    {
        "exec_shell",
        "exec_shell_wait",
        "exec_shell_interact",
        "exec_wait",
        "exec_interact",
    }
)


def should_default_defer_tool(name: str, mode: str) -> bool:
    """Whether a tool should be deferred (lazy-loaded) by default."""
    if mode == "yolo":
        return False
    if mode == "agent" and name in _SHELL_TOOLS:
        return False
    return name not in _ALWAYS_ACTIVE_TOOLS


def apply_native_tool_deferral(
    catalog: list[dict[str, Any]], mode: str
) -> None:
    """Set ``defer_loading`` on each native tool dict in-place."""
    for tool in catalog:
        fn = tool.get("function", tool)
        tool_name = fn.get("name", "")
        fn["defer_loading"] = should_default_defer_tool(tool_name, mode)


def apply_mcp_tool_deferral(
    catalog: list[dict[str, Any]], mode: str
) -> None:
    """Set ``defer_loading`` on each MCP tool dict in-place."""
    keep_loaded = frozenset(
        {
            "list_mcp_resources",
            "list_mcp_resource_templates",
            "mcp_read_resource",
            "read_mcp_resource",
            "mcp_get_prompt",
        }
    )
    for tool in catalog:
        fn = tool.get("function", tool)
        tool_name = fn.get("name", "")
        fn["defer_loading"] = mode != "yolo" and tool_name not in keep_loaded


def build_model_tool_catalog(
    native_tools: list[dict[str, Any]],
    mcp_tools: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    """Combine native and MCP tools with deferral applied and sorted."""
    apply_native_tool_deferral(native_tools, mode)
    apply_mcp_tool_deferral(mcp_tools, mode)

    def _sort_key(t: dict[str, Any]) -> str:
        fn = t.get("function", t)
        name = fn.get("name", "") if isinstance(fn, dict) else ""
        return str(name)

    native_tools.sort(key=_sort_key)
    mcp_tools.sort(key=_sort_key)
    return native_tools + mcp_tools


# --- Advanced tooling injection (Rust tool_catalog.rs:120-180) ------------


def ensure_advanced_tooling(tools: list[dict[str, Any]]) -> None:
    """Ensure built-in advanced tools (code_execution, tool_search) are present."""
    existing = set()
    for t in tools:
        fn = t.get("function", t)
        existing.add(fn.get("name"))

    if CODE_EXECUTION_TOOL_NAME not in existing:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": CODE_EXECUTION_TOOL_NAME,
                    "description": (
                        "Execute Python code in a local sandboxed runtime "
                        "and return stdout/stderr/return_code as JSON."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python source code to execute.",
                            }
                        },
                        "required": ["code"],
                    },
                    "allowed_callers": ["direct"],
                    "defer_loading": False,
                },
            }
        )

    if TOOL_SEARCH_REGEX_NAME not in existing:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": TOOL_SEARCH_REGEX_NAME,
                    "description": (
                        "Search deferred tool definitions using a regex query "
                        "and return matching tool references."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Regex pattern to search tool "
                                    "names/descriptions/schema."
                                ),
                            }
                        },
                        "required": ["query"],
                    },
                    "allowed_callers": ["direct"],
                    "defer_loading": False,
                },
            }
        )

    if TOOL_SEARCH_BM25_NAME not in existing:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": TOOL_SEARCH_BM25_NAME,
                    "description": (
                        "Search deferred tool definitions using natural-language "
                        "matching and return matching tool references."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural language query for tool discovery.",
                            }
                        },
                        "required": ["query"],
                    },
                    "allowed_callers": ["direct"],
                    "defer_loading": False,
                },
            }
        )


# --- Active tool set (Rust tool_catalog.rs:182-240) ----------------------


def initial_active_tools(tools: list[dict[str, Any]]) -> set[str]:
    """Get initial set of active (non-deferred) tool names."""
    active: set[str] = set()
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name")
        if not isinstance(name, str):
            continue
        if not fn.get("defer_loading", False) or is_tool_search_tool(name):
            active.add(name)
    if not active and tools:
        fn = tools[0].get("function", tools[0])
        first = fn.get("name")
        if isinstance(first, str):
            active.add(first)
    return active


def active_tools_for_step(
    tools: list[dict[str, Any]],
    active_names: set[str],
    force_update_plan_first: bool,
) -> list[dict[str, Any]]:
    """Filter the catalog to only active tools for this turn step."""
    if force_update_plan_first:
        for t in tools:
            fn = t.get("function", t)
            if fn.get("name") == "update_plan":
                return [t]
        return []

    head: list[dict[str, Any]] = []
    tail: list[dict[str, Any]] = []
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name")
        if name not in active_names:
            continue
        if fn.get("defer_loading", False):
            tail.append(t)
        else:
            head.append(t)
    return head + tail


def maybe_activate_requested_deferred_tool(
    tool_name: str,
    catalog: list[dict[str, Any]],
    active_tools: set[str],
) -> bool:
    """Activate a deferred tool if the model requests it. Returns True if activated."""
    if tool_name in active_tools:
        return False
    for t in catalog:
        fn = t.get("function", t)
        if fn.get("name") == tool_name and fn.get("defer_loading", False):
            active_tools.add(tool_name)
            return True
    return False


# --- Tool search (Rust tool_catalog.rs:242-302) --------------------------


def _tool_search_haystack(tool: dict[str, Any]) -> str:
    fn = tool.get("function", tool)
    name = fn.get("name", "").lower()
    desc = fn.get("description", "").lower()
    schema = json.dumps(fn.get("parameters", {})).lower()
    return f"{name}\n{desc}\n{schema}"


def discover_tools_with_regex(
    catalog: list[dict[str, Any]], query: str
) -> list[str]:
    """Search tool catalog by regex; return up to 5 matching names."""
    try:
        pattern = re.compile(query)
    except re.error as exc:
        raise ToolError(f"Invalid regex query: {exc}") from exc

    matches: list[str] = []
    for tool in catalog:
        fn = tool.get("function", tool)
        name = fn.get("name", "")
        if is_tool_search_tool(name):
            continue
        if pattern.search(_tool_search_haystack(tool)):
            matches.append(name)
            if len(matches) >= 5:
                break
    return matches


def discover_tools_with_bm25_like(
    catalog: list[dict[str, Any]], query: str
) -> list[str]:
    """Simple BM25-like scoring: count query term hits in tool metadata."""
    terms = [t.strip().lower() for t in query.split() if t.strip()]
    if not terms:
        return []

    scored: list[tuple[int, str]] = []
    for tool in catalog:
        fn = tool.get("function", tool)
        name = fn.get("name", "")
        if is_tool_search_tool(name):
            continue
        hay = _tool_search_haystack(tool)
        score = 0
        for term in terms:
            if term in hay:
                score += 1
            if term in name.lower():
                score += 2
        if score > 0:
            scored.append((score, name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in scored[:5]]


# --- Edit distance & suggestions (Rust tool_catalog.rs:304-389) ----------


def edit_distance(a: str, b: str) -> int:
    """Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, a_ch in enumerate(a):
        curr[0] = i + 1
        for j, b_ch in enumerate(b):
            cost = 0 if a_ch == b_ch else 1
            curr[j + 1] = min(prev[j + 1] + 1, curr[j] + 1, prev[j] + cost)
        prev, curr = curr, prev
    return prev[len(b)]


def suggest_tool_names(
    catalog: list[dict[str, Any]], requested: str, limit: int = 3
) -> list[str]:
    """Suggest similar tool names from the catalog."""
    req = requested.strip().lower()
    if not req or limit <= 0:
        return []

    candidates: list[tuple[int, int, str]] = []
    for tool in catalog:
        fn = tool.get("function", tool)
        name = fn.get("name", "")
        lower_name = name.lower()
        prefix_match = lower_name.startswith(req) or req.startswith(lower_name)
        contains_match = req in lower_name or lower_name in req
        dist = edit_distance(lower_name, req)
        close_typo = dist <= 3
        if not (prefix_match or contains_match or close_typo):
            continue
        rank = 0 if prefix_match else (1 if contains_match else 2)
        candidates.append((rank, dist, name))

    candidates.sort()
    seen: set[str] = set()
    result: list[str] = []
    for _, _, name in candidates:
        if name not in seen:
            seen.add(name)
            result.append(name)
            if len(result) >= limit:
                break
    return result


def missing_tool_error_message(
    tool_name: str, catalog: list[dict[str, Any]]
) -> str:
    """Build an error message for a missing tool, with suggestions."""
    suggestions = suggest_tool_names(catalog, tool_name, 3)
    if not suggestions:
        return (
            f"Tool '{tool_name}' is not available in the current tool catalog. "
            f"Verify mode/feature flags, or use {TOOL_SEARCH_BM25_NAME} with a short query."
        )
    return (
        f"Tool '{tool_name}' is not available in the current tool catalog. "
        f"Did you mean: {', '.join(suggestions)}? "
        f"You can also use {TOOL_SEARCH_BM25_NAME} to discover tools."
    )


# --- Built-in tool executors (Rust tool_catalog.rs:407-475) ---------------


def execute_tool_search(
    tool_name: str,
    input_data: dict[str, Any],
    catalog: list[dict[str, Any]],
    active_tools: set[str],
) -> ToolResult:
    """Execute a tool search (regex or BM25-like) and activate discovered tools."""
    query = input_data.get("query", "")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("Missing required field 'query'")

    if tool_name == TOOL_SEARCH_REGEX_NAME:
        discovered = discover_tools_with_regex(catalog, query)
    else:
        discovered = discover_tools_with_bm25_like(catalog, query)

    for name in discovered:
        active_tools.add(name)

    references = [
        {"type": "tool_reference", "tool_name": name} for name in discovered
    ]
    payload = {
        "type": "tool_search_tool_search_result",
        "tool_references": references,
    }
    return ToolResult(
        success=True,
        content=json.dumps(payload),
        metadata={"tool_references": discovered},
    )


async def execute_code_execution_tool(
    input_data: dict[str, Any], workspace: Path
) -> ToolResult:
    """Run model-provided Python code in a subprocess."""
    code = input_data.get("code", "")
    if not isinstance(code, str) or not code.strip():
        raise ToolError("Missing required field 'code'")

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "python3",
                "-c",
                code,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ),
            timeout=120,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=120
        )
    except asyncio.TimeoutError as exc:
        raise ToolError("code_execution timed out after 120s") from exc

    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
    return_code = proc.returncode or 0
    success = return_code == 0

    payload = {
        "type": "code_execution_result",
        "stdout": stdout,
        "stderr": stderr,
        "return_code": return_code,
        "content": [],
    }
    return ToolResult(
        success=success,
        content=json.dumps(payload),
        metadata=payload,
    )
