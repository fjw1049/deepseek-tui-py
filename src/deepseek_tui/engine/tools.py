"""Tool catalog and response parser.

Consolidates tool_catalog.py and tool_parser.py.
Deferred tool catalog and built-in advanced tool helpers.

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

from deepseek_tui.tools.registry import ToolError, ToolResult
from dataclasses import dataclass

# --- Constants ------------------------------------------------------------

MULTI_TOOL_PARALLEL_NAME = "multi_tool_use.parallel"
REQUEST_USER_INPUT_NAME = "request_user_input"
CODE_EXECUTION_TOOL_NAME = "code_execution"

TOOL_SEARCH_REGEX_NAME = "tool_search_tool_regex"
TOOL_SEARCH_BM25_NAME = "tool_search_tool_bm25"

# --- Tool search predicate ------------------------------------------------


def is_tool_search_tool(name: str) -> bool:
    return name in (TOOL_SEARCH_REGEX_NAME, TOOL_SEARCH_BM25_NAME)


# --- Deferred loading policy ----------------------------------------------

_ALWAYS_ACTIVE_TOOLS = frozenset(
    {
        "read_file",
        "list_dir",
        "grep_files",
        "file_search",
        "diagnostics",
        "project_map",
        "load_skill",
        "note",
        "recall_archive",
        MULTI_TOOL_PARALLEL_NAME,
        "update_plan",
        "checklist_write",
        "checklist_add",
        "checklist_update",
        "checklist_list",
        "task_create",
        "task_list",
        "task_read",
        "task_gate_run",
        "task_shell_start",
        "task_shell_wait",
        # Sub-agent orchestration — keep visible alongside task_* so the
        # model does not reach for task_create when the user asks for
        # agent_spawn (both families were originally deferred; task_* was
        # promoted to always-active in Python and created a selection bias).
        "agent_spawn",
        "agent_result",
        "agent_wait",
        "agent_list",
        "agent_cancel",
        "agent_send_input",
        "resume_agent",
        "delegate_to_agent",
        "workflow",
        "github_issue_context",
        "github_pr_context",
        "web_search",
        "fetch_url",
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


_WORKFLOW_TOOLS = frozenset({"workflow"})


def should_default_defer_tool(name: str, mode: str) -> bool:
    """Whether a tool should be deferred (lazy-loaded) by default."""
    if mode == "yolo":
        return False
    if mode == "agent" and name in _SHELL_TOOLS:
        return False
    if mode == "workflow" and name in _WORKFLOW_TOOLS:
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


# --- Advanced tooling injection -------------------------------------------


def ensure_advanced_tooling(
    tools: list[dict[str, Any]],
    *,
    include_tool_search: bool = True,
    include_code_execution: bool = True,
) -> None:
    """Ensure built-in advanced tools (code_execution, tool_search) are present."""
    existing = set()
    for t in tools:
        fn = t.get("function", t)
        existing.add(fn.get("name"))

    if CODE_EXECUTION_TOOL_NAME not in existing and include_code_execution:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": CODE_EXECUTION_TOOL_NAME,
                    "description": (
                        "Execute Python code in a local subprocess (workspace "
                        "cwd, no sandbox) and return stdout/stderr/return_code "
                        "as JSON. Requires user approval."
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

    if TOOL_SEARCH_REGEX_NAME not in existing and include_tool_search:
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

    if TOOL_SEARCH_BM25_NAME not in existing and include_tool_search:
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


# --- Active tool set ------------------------------------------------------


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


# --- Tool search ----------------------------------------------------------


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


# --- Edit distance & suggestions ------------------------------------------


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


# --- Built-in tool executors ----------------------------------------------


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

    proc = None
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
        # Reap the subprocess on timeout; otherwise it keeps running and
        # accumulates as an orphan across repeated timeouts.
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
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


# Tool call parsing for text-based and streaming fragments.



@dataclass
class ParsedToolCall:
    """A parsed tool call from text or stream."""

    name: str
    args: dict[str, object] | None
    id: str


@dataclass
class ParseResult:
    """Result of parsing text for tool calls."""

    clean_text: str
    tool_calls: list[ParsedToolCall]


_TOOL_CALL_REGEX: re.Pattern[str] | None = None
_XML_TOOL_CALL_REGEX: re.Pattern[str] | None = None
_INVOKE_REGEX: re.Pattern[str] | None = None
_THINKING_REGEX: re.Pattern[str] | None = None


def _get_tool_call_regex() -> re.Pattern[str]:
    """Get compiled regex for [TOOL_CALL]...[/TOOL_CALL] blocks."""
    global _TOOL_CALL_REGEX
    if _TOOL_CALL_REGEX is None:
        _TOOL_CALL_REGEX = re.compile(r"(?s)\[TOOL_CALL\]\s*(.*?)\s*\[/TOOL_CALL\]")
    return _TOOL_CALL_REGEX


def _get_xml_tool_call_regex() -> re.Pattern[str]:
    """Get compiled regex for <deepseek:tool_call>...</deepseek:tool_call>."""
    global _XML_TOOL_CALL_REGEX
    if _XML_TOOL_CALL_REGEX is None:
        _XML_TOOL_CALL_REGEX = re.compile(
            r"(?s)<(?:deepseek:)?tool_call[^>]*>\s*(.*?)\s*</(?:deepseek:)?tool_call>"
        )
    return _XML_TOOL_CALL_REGEX


def _get_invoke_regex() -> re.Pattern[str]:
    """Get compiled regex for <invoke name="...">...</invoke> patterns."""
    global _INVOKE_REGEX
    if _INVOKE_REGEX is None:
        _INVOKE_REGEX = re.compile(
            r'(?s)<invoke\s+name\s*=\s*"([^"]+)"[^>]*>(.*?)</invoke>'
        )
    return _INVOKE_REGEX


def _get_thinking_regex() -> re.Pattern[str]:
    """Get compiled regex for thinking/think tags."""
    global _THINKING_REGEX
    if _THINKING_REGEX is None:
        _THINKING_REGEX = re.compile(r"(?s)</?(?:think|thinking)[^>]*>")
    return _THINKING_REGEX


def parse_tool_calls(text: str) -> ParseResult:
    """Parse tool calls from text content.

    Supports multiple formats:
    - [TOOL_CALL] {...} [/TOOL_CALL]
    - <deepseek:tool_call><invoke name="...">...</invoke></deepseek:tool_call>
    - <invoke name="...">...</invoke> (standalone)

    Returns clean text (markers removed) and parsed tool calls.
    """
    tool_calls: list[ParsedToolCall] = []
    clean_text = text
    id_counter = 0

    # First, remove thinking tags
    thinking_regex = _get_thinking_regex()
    clean_text = thinking_regex.sub("", clean_text)

    # Parse [TOOL_CALL] format
    regex = _get_tool_call_regex()
    for match in regex.finditer(text):
        inner = match.group(1).strip() if match.group(1) else ""
        if inner:
            parsed = _parse_tool_call_inner(inner, id_counter)
            if parsed:
                tool_calls.append(parsed)
                id_counter += 1
        clean_text = clean_text.replace(match.group(0), "")

    # Parse XML-style <deepseek:tool_call> or <tool_call> format
    xml_regex = _get_xml_tool_call_regex()
    for match in xml_regex.finditer(text):
        inner = match.group(1).strip() if match.group(1) else ""
        if inner:
            parsed = _parse_invoke_block(inner, id_counter) or _parse_tool_call_inner(
                inner, id_counter
            )
            if parsed:
                tool_calls.append(parsed)
                id_counter += 1
        clean_text = clean_text.replace(match.group(0), "")

    # Also parse standalone <invoke> blocks
    invoke_regex = _get_invoke_regex()
    for match in invoke_regex.finditer(clean_text):
        tool_name = match.group(1) if match.group(1) else ""
        inner = match.group(2) if match.group(2) else ""
        if tool_name:
            args = _parse_xml_parameters(inner)
            id_counter += 1
            tool_calls.append(
                ParsedToolCall(name=tool_name, args=args, id=f"xml_tool_{id_counter}")
            )
        clean_text = clean_text.replace(match.group(0), "")

    # Clean up extra whitespace and empty lines
    clean_text = "\n".join(
        line for line in clean_text.split("\n") if line.strip()
    ).strip()

    return ParseResult(clean_text=clean_text, tool_calls=tool_calls)


def _parse_invoke_block(content: str, id_counter: int) -> ParsedToolCall | None:
    """Parse an <invoke> block into a tool call."""
    invoke_regex = _get_invoke_regex()
    match = invoke_regex.search(content)
    if not match:
        return None

    tool_name = match.group(1) if match.group(1) else ""
    inner = match.group(2) if match.group(2) else ""

    if not tool_name:
        return None

    args = _parse_xml_parameters(inner)
    return ParsedToolCall(
        name=tool_name, args=args, id=f"xml_tool_{id_counter + 1}"
    )


def _parse_xml_parameters(content: str) -> dict[str, object]:
    """Parse XML-style parameters like <parameter name="foo">value</parameter>."""
    result = {}

    # Try parsing <parameter name="...">value</parameter>
    param_regex = re.compile(
        r'<(?:parameter|param)\s+name\s*=\s*"([^"]+)"[^>]*>(.*?)</(?:parameter|param)>',
        re.DOTALL,
    )
    for match in param_regex.finditer(content):
        name = match.group(1)
        value_str = match.group(2).strip() if match.group(2) else ""
        if name and value_str:
            try:
                result[name] = json.loads(value_str)
            except json.JSONDecodeError:
                result[name] = value_str

    # Also try parsing <tagname>value</tagname> format
    simple_tag_regex = re.compile(
        r"<([a-zA-Z_][a-zA-Z0-9_]*)>(.*?)</([a-zA-Z_][a-zA-Z0-9_]*)>",
        re.DOTALL,
    )
    for match in simple_tag_regex.finditer(content):
        name = match.group(1)
        value_str = match.group(2).strip() if match.group(2) else ""
        close = match.group(3)

        if name != close:
            continue
        if name in ["invoke", "tool_call", "parameter", "param"]:
            continue
        if name not in result and value_str:
            try:
                result[name] = json.loads(value_str)
            except json.JSONDecodeError:
                result[name] = value_str

    return result if result else {}


def _parse_tool_call_inner(inner: str, id_counter: int) -> ParsedToolCall | None:
    """Parse the inner content of a TOOL_CALL block."""
    # Try to parse as JSON first
    try:
        json_obj = json.loads(inner)
        if isinstance(json_obj, dict):
            return _parse_from_json(json_obj, id_counter)
    except json.JSONDecodeError:
        pass

    # Try the arrow syntax: {tool => "name", args => {...}}
    parsed = _parse_arrow_syntax(inner, id_counter)
    if parsed:
        return parsed

    # Try to extract tool name and args from any format
    return _parse_flexible_format(inner, id_counter)


def _parse_from_json(obj: dict[str, object], id_counter: int) -> ParsedToolCall | None:
    """Parse from JSON object."""
    # Try different field names for the tool name
    name: str | None = None
    for key in ["tool", "name", "function"]:
        val = obj.get(key)
        if isinstance(val, str):
            name = val
            break

    if not name:
        return None

    # Try different field names for the arguments
    args: dict[str, object] = {}
    for key in ["args", "arguments", "input", "parameters"]:
        val = obj.get(key)
        if isinstance(val, dict):
            args = val
            break

    return ParsedToolCall(
        name=name, args=args, id=f"text_tool_{id_counter + 1}"
    )


def _parse_arrow_syntax(inner: str, id_counter: int) -> ParsedToolCall | None:
    """Parse the arrow syntax: {tool => "name", args => {...}}."""
    # Extract tool name
    tool_regex = re.compile(r'tool\s*=>\s*"([^"]+)"')
    match = tool_regex.search(inner)
    if not match:
        return None

    name = match.group(1)

    # Extract args - try to find the JSON object after "args =>"
    args: dict[str, object] = {}
    args_start = inner.find("args =>")
    if args_start >= 0:
        args_str = inner[args_start + 7 :].strip()

        # Try to parse as JSON first
        try:
            parsed_args = json.loads(args_str)
            if isinstance(parsed_args, dict):
                args = parsed_args
        except json.JSONDecodeError:
            # Try to extract content between braces
            brace_start = args_str.find("{")
            if brace_start >= 0:
                brace_count = 0
                end_idx = brace_start
                for i, c in enumerate(args_str[brace_start:]):
                    if c == "{":
                        brace_count += 1
                    elif c == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = brace_start + i + 1
                            break

                content = args_str[brace_start + 1 : end_idx - 1]

                # Try to parse as JSON
                try:
                    parsed_args = json.loads("{" + content + "}")
                    if isinstance(parsed_args, dict):
                        args = parsed_args
                except json.JSONDecodeError:
                    # Try CLI-style args
                    args = _parse_cli_style_args(content)

    return ParsedToolCall(
        name=name, args=args, id=f"text_tool_{id_counter + 1}"
    )


def _parse_cli_style_args(content: str) -> dict[str, object]:
    """Parse CLI-style arguments: --arg_name "value" or --arg_name value."""
    result = {}

    # Pattern: --arg_name "value" or --arg_name 'value' or --arg_name value
    arg_regex = re.compile(r'--([a-zA-Z_][a-zA-Z0-9_]*)\s+(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
    for match in arg_regex.finditer(content):
        arg_name = match.group(1)
        value = (
            match.group(2)
            or match.group(3)
            or match.group(4)
            or ""
        )
        if arg_name and value:
            try:
                result[arg_name] = json.loads(value)
            except json.JSONDecodeError:
                result[arg_name] = value

    # Also try simple key=value format
    kv_regex = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*[:=]\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
    for match in kv_regex.finditer(content):
        key = match.group(1)
        if key not in result:
            value = (
                match.group(2)
                or match.group(3)
                or match.group(4)
                or ""
            )
            if value:
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    result[key] = value

    return result


def _parse_flexible_format(inner: str, id_counter: int) -> ParsedToolCall | None:
    """Try to parse a flexible format (tool:, name:, function:)."""
    pattern = r'(?:tool|name|function)\s*[:=]\s*"?([a-zA-Z_][a-zA-Z0-9_]*)"?'
    match = re.search(pattern, inner)
    if not match:
        return None

    name = match.group(1)

    # Try to extract args/input as JSON
    extracted = _extract_json_object(inner)
    args: dict[str, object] = extracted if extracted else {}

    return ParsedToolCall(
        name=name, args=args, id=f"text_tool_{id_counter + 1}"
    )


def _extract_json_object(text: str) -> dict[str, object] | None:
    """Extract the first JSON object from a string."""
    start = text.find("{")
    if start < 0:
        return None

    brace_count = 0
    end_idx = start

    for i, c in enumerate(text[start:]):
        if c == "{":
            brace_count += 1
        elif c == "}":
            brace_count -= 1
            if brace_count == 0:
                end_idx = start + i + 1
                break

    json_str = text[start:end_idx]
    try:
        result = json.loads(json_str)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        return None


def has_tool_call_markers(text: str) -> bool:
    """Check if text contains tool call markers (either format)."""
    return (
        "[TOOL_CALL]" in text
        or "<deepseek:tool_call" in text
        or "<tool_call" in text
        or "<invoke " in text
    )
