"""MCP server configuration models and ``mcp.json`` loading."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUTS: dict[str, float] = {
    "connect_timeout": 10.0,
    "execute_timeout": 60.0,
    "read_timeout": 120.0,
}


@dataclass(slots=True)
class McpServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    enabled: bool = True
    required: bool = False
    connect_timeout: float = 10.0
    execute_timeout: float = 60.0
    read_timeout: float = 120.0
    tool_filter: ToolFilter | None = None
    # Deferred startup: excluded from eager start_all / background warm
    # connects; the server process only spawns on first tool call or
    # discovery. ``None`` means "not specified" so callers (e.g. the
    # plugin loader) can apply their own default.
    lazy: bool | None = None
    # Declared capability hints (e.g. from a plugin manifest's
    # ``permissions``) consumed by the approval presentation layer.
    capabilities: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ToolFilter:
    """Filter which tools are exposed from an MCP server."""

    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)

    def accepts(self, tool_name: str) -> bool:
        if self.deny and tool_name in self.deny:
            return False
        if self.allow:
            return tool_name in self.allow
        return True


# --- config loading ---------------------------------------------------------


def load_mcp_config(path: Path) -> list[McpServerConfig]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid MCP config: {path}")
    return servers_from_document(data)


def servers_from_document(data: dict[str, Any]) -> list[McpServerConfig]:
    """Parse an in-memory mcp.json-shaped document into server configs."""
    defaults = data.get("timeouts", {})
    if not isinstance(defaults, dict):
        defaults = {}
    servers = data.get("servers", data.get("mcpServers", {}))
    if not isinstance(servers, dict):
        raise ValueError("Invalid MCP servers table")
    return [
        _server_from_raw(name, raw, defaults)
        for name, raw in servers.items()
        if isinstance(name, str) and isinstance(raw, dict)
    ]


def _server_from_raw(
    name: str,
    raw: dict[str, Any],
    defaults: dict[str, Any],
) -> McpServerConfig:
    enabled_tools = _string_list(raw.get("enabled_tools"))
    disabled_tools = _string_list(raw.get("disabled_tools"))
    command = raw.get("command")
    url = raw.get("url")
    return McpServerConfig(
        name=name,
        command=command if isinstance(command, str) else None,
        args=_string_list(raw.get("args")),
        env=_string_dict(raw.get("env")),
        url=url if isinstance(url, str) else None,
        enabled=bool(raw.get("enabled", not bool(raw.get("disabled", False)))),
        required=bool(raw.get("required", False)),
        connect_timeout=float(
            raw.get(
                "connect_timeout",
                defaults.get("connect_timeout", DEFAULT_TIMEOUTS["connect_timeout"]),
            )
        ),
        execute_timeout=float(
            raw.get(
                "execute_timeout",
                defaults.get("execute_timeout", DEFAULT_TIMEOUTS["execute_timeout"]),
            )
        ),
        read_timeout=float(
            raw.get(
                "read_timeout",
                defaults.get("read_timeout", DEFAULT_TIMEOUTS["read_timeout"]),
            )
        ),
        tool_filter=ToolFilter(allow=enabled_tools, deny=disabled_tools)
        if enabled_tools or disabled_tools
        else None,
        lazy=bool(raw["lazy"]) if "lazy" in raw else None,
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}
