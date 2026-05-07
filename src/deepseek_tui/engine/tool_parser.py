"""Tool call parsing for text-based and streaming fragments.

Mirrors `crates/tui/src/core/tool_parser.rs` (510 lines) for text-based legacy format support.
Mirrors `crates/tui/src/core/engine/dispatch.rs:151-220` for stream fragment reassembly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


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


def parse_tool_input(buffer: str) -> dict[str, object] | None:
    """Parse streaming tool input JSON fragments.

    Handles partial/incomplete JSON during streaming by:
    1. Trying direct JSON parse
    2. Stripping code fences (```)
    3. Handling double-quoted strings
    4. Extracting balanced braces for partial JSON

    This is the core stream fragment reassembly function.
    """
    trimmed = buffer.strip()
    if not trimmed:
        return None

    # Try direct JSON parse
    try:
        result = json.loads(trimmed)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try stripping code fences
    stripped = _strip_code_fences(trimmed)
    if stripped:
        try:
            result = json.loads(stripped)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Try handling double-quoted string containing JSON
    try:
        inner = json.loads(trimmed)
        if isinstance(inner, str):
            result = json.loads(inner)
            if isinstance(result, dict):
                return result
    except json.JSONDecodeError:
        pass

    # Try extracting balanced segment (partial JSON)
    segment = _extract_json_segment(trimmed)
    if segment:
        try:
            result = json.loads(segment)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


def _strip_code_fences(text: str) -> str | None:
    """Remove ``` code fence markers from text."""
    if "```" not in text:
        return None

    lines = []
    for line in text.split("\n"):
        if not line.strip().startswith("```"):
            lines.append(line)

    stripped = "\n".join(lines).strip()
    return stripped if stripped else None


def _extract_json_segment(text: str) -> str | None:
    """Extract the first complete JSON segment (object or array)."""
    # Try extracting balanced braces first, then brackets
    result = _extract_balanced_segment(text, "{", "}")
    if result:
        return result
    return _extract_balanced_segment(text, "[", "]")


def _extract_balanced_segment(text: str, open_char: str, close_char: str) -> str | None:
    """Extract a balanced segment between open_char and close_char."""
    start = text.find(open_char)
    if start < 0:
        return None

    depth = 0
    end_idx = None

    for i, c in enumerate(text[start:]):
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                end_idx = start + i + 1
                break

    if end_idx is None:
        return None

    return text[start:end_idx]
