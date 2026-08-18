"""Tool catalog and response parser.

The streaming turn loop owns when tools are offered or executed. This module
owns catalog merge, missing-tool suggestions, and text-based tool-call parsing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from dataclasses import dataclass

import logging

logger = logging.getLogger(__name__)

# --- Constants ------------------------------------------------------------

REQUEST_USER_INPUT_NAME = "request_user_input"

# Tools visible/executable while interaction mode is plan. Used to filter a
# shared (agent-built) registry when mode flips mid-session without rebuild.
PLAN_MODE_TOOL_ALLOWLIST = frozenset(
    {
        "agent",
        "checklist",
        "fetch_url",
        "file_search",
        "grep_files",
        "list_mcp_resources",
        "load_skill",
        "read_file",
        "read_mcp_resource",
        REQUEST_USER_INPUT_NAME,
        "task_list",
        "task_output",
        "update_plan",
        "web_search",
        "exit_plan_mode",
    }
)

def build_model_tool_catalog(
    native_tools: list[dict[str, Any]],
    mcp_tools: list[dict[str, Any]],
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """Combine native and MCP tools, sorted by name.

    ``mode`` is accepted for call-site compatibility and ignored: the full
    discovered catalog is sent as-is.
    """
    del mode

    def _sort_key(t: dict[str, Any]) -> str:
        fn = t.get("function", t)
        name = fn.get("name", "") if isinstance(fn, dict) else ""
        return str(name)

    native_tools.sort(key=_sort_key)
    mcp_tools.sort(key=_sort_key)
    # Native tools win name collisions (dispatch resolves registry-first), so
    # drop shadowed MCP entries to avoid duplicate function names reaching
    # the model.
    native_names = {_sort_key(t) for t in native_tools}
    deduped_mcp: list[dict[str, Any]] = []
    for tool in mcp_tools:
        name = _sort_key(tool)
        if name in native_names:
            logger.warning(
                "MCP tool %r shadows a native tool with the same name; "
                "dropping the MCP entry from the model catalog",
                name,
            )
            continue
        deduped_mcp.append(tool)
    return native_tools + deduped_mcp


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
            "Verify mode, feature flags, or the tool name."
        )
    return (
        f"Tool '{tool_name}' is not available in the current tool catalog. "
        f"Did you mean: {', '.join(suggestions)}?"
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
