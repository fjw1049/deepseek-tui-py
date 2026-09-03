"""Outbound MCP client package — connect to external MCP servers.

Module map:

- ``config`` — server models and JSON loading
- ``transport`` — stdio / SSE channels
- ``client`` — single-server JSON-RPC
- ``manager`` — pool, discovery, cache, preload
- ``store`` — ``mcp.json`` CRUD and status snapshots
- ``actions`` — shared CLI/TUI config mutations
- ``execute`` — Engine tool-call adapter

Built-in resource tools live in ``deepseek_tui.tools.mcp``.
"""

from .client import McpError
from .manager import McpManager

__all__ = ["McpError", "McpManager"]
