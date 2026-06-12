"""Outbound MCP client package — connect to external MCP servers.

Module map:

- ``config`` — server models and JSON loading
- ``transport`` — stdio / SSE channels
- ``client`` — single-server JSON-RPC
- ``manager`` — pool, discovery, cache, preload
- ``store`` — ``mcp.json`` CRUD and status snapshots
- ``actions`` — shared CLI/TUI config mutations
- ``execute`` — Engine tool-call adapter

Built-in resource/prompt tools live in ``deepseek_tui.tools.mcp``.
"""

from .client import McpClient, McpError, McpToolDescriptor, parse_qualified_tool_name, qualify_tool_name
from .config import DEFAULT_TIMEOUTS, McpServerConfig, ToolFilter, load_mcp_config
from .manager import (
    DEFAULT_PRELOAD_TIMEOUT_S,
    McpManager,
    McpPreloadSnapshot,
    raise_if_required_mcp_failed,
)
from .store import (
    McpManagerSnapshot,
    McpWriteStatus,
    add_server_config,
    discover_manager_snapshot,
    format_manager_snapshot,
    init_config,
    manager_snapshot_from_config,
    remove_server_config,
    resolve_mcp_config_path,
    set_server_enabled,
    validate_mcp_config_path,
)

__all__ = [
    "DEFAULT_PRELOAD_TIMEOUT_S",
    "DEFAULT_TIMEOUTS",
    "McpClient",
    "McpError",
    "McpManager",
    "McpManagerSnapshot",
    "McpPreloadSnapshot",
    "McpServerConfig",
    "McpToolDescriptor",
    "McpWriteStatus",
    "ToolFilter",
    "add_server_config",
    "discover_manager_snapshot",
    "format_manager_snapshot",
    "init_config",
    "load_mcp_config",
    "manager_snapshot_from_config",
    "parse_qualified_tool_name",
    "qualify_tool_name",
    "raise_if_required_mcp_failed",
    "remove_server_config",
    "resolve_mcp_config_path",
    "set_server_enabled",
    "validate_mcp_config_path",
]
