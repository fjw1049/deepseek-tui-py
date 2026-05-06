from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deepseek_tui.mcp.config import McpServerConfig, ToolFilter


def load_mcp_config(path: Path) -> list[McpServerConfig]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid MCP config: {path}")
    defaults = data.get("timeouts", {})
    if not isinstance(defaults, dict):
        defaults = {}
    servers = data.get("servers", data.get("mcpServers", {}))
    if not isinstance(servers, dict):
        raise ValueError(f"Invalid MCP servers table: {path}")
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
        connect_timeout=float(raw.get("connect_timeout", defaults.get("connect_timeout", 10.0))),
        execute_timeout=float(raw.get("execute_timeout", defaults.get("execute_timeout", 60.0))),
        read_timeout=float(raw.get("read_timeout", defaults.get("read_timeout", 120.0))),
        tool_filter=ToolFilter(allow=enabled_tools, deny=disabled_tools)
        if enabled_tools or disabled_tools
        else None,
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}
