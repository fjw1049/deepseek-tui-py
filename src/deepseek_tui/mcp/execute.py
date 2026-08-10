"""Execute external MCP tools — shared by Engine and AppRuntime."""

from __future__ import annotations



import json
from typing import Any

from deepseek_tui.engine.dispatch import is_mcp_tool
from deepseek_tui.mcp.client import McpError
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.mcp.schema_hints import (
    enrich_mcp_argument_error,
    format_schema_hint,
    looks_like_argument_error,
)
from deepseek_tui.tools.registry import ToolError, ToolResult

_MCP_READ_ALIASES = frozenset({"mcp_read_resource", "read_mcp_resource"})


def normalize_mcp_bridge_tool_name(name: str) -> str:
    """Map MCP bridge aliases onto registered tool names."""
    if name == "mcp_read_resource":
        return "read_mcp_resource"
    return name


def mcp_response_to_tool_result(
    name: str,
    payload: dict[str, Any],
    *,
    parameters: dict[str, Any] | None = None,
) -> ToolResult:
    """Convert an MCP ``tools/call`` payload into a :class:`ToolResult`."""
    content_parts: list[str] = []
    for block in payload.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            content_parts.append(block.get("text", ""))
    content = "\n".join(content_parts) if content_parts else json.dumps(payload)
    is_error = bool(payload.get("isError", False))
    if is_error and looks_like_argument_error(content):
        content = f"{content}\n\n{format_schema_hint(parameters)}"
    return ToolResult(success=not is_error, content=content, metadata={"mcp_tool": name})


async def execute_external_mcp_tool(
    manager: McpManager,
    tool_name: str,
    arguments: dict[str, Any],
) -> ToolResult:
    """Call a qualified ``mcp_<server>_<tool>`` tool via :class:`McpManager`."""
    if not is_mcp_tool(tool_name):
        raise ToolError(f"Not an MCP tool: {tool_name}")
    parameters = manager.lookup_tool_parameters(tool_name)
    try:
        payload = await manager.call_tool(tool_name, arguments)
    except McpError as exc:
        raise ToolError(
            enrich_mcp_argument_error(tool_name, str(exc), parameters)
        ) from exc
    return mcp_response_to_tool_result(tool_name, payload, parameters=parameters)


def is_external_mcp_tool(tool_name: str, registry_contains: bool) -> bool:
    """True when the name is an external MCP tool not served by the registry."""
    return is_mcp_tool(tool_name) and not registry_contains and tool_name not in _MCP_READ_ALIASES
