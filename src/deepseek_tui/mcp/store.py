"""``mcp.json`` CRUD and human-readable status snapshots for CLI / TUI / GUI."""

from __future__ import annotations



import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import Config
from deepseek_tui.mcp.config import DEFAULT_TIMEOUTS, McpServerConfig, load_mcp_config
from deepseek_tui.utils import write_json_atomic


class McpWriteStatus(str, Enum):
    CREATED = "created"
    OVERWRITTEN = "overwritten"
    SKIPPED_EXISTS = "skipped_exists"


def validate_mcp_config_path(path: Path) -> None:
    """Reject unsafe MCP config paths (mirrors Rust ``validate_mcp_config_path``)."""
    if not str(path).strip():
        raise ValueError("MCP config path is empty")
    if ".." in path.parts:
        raise ValueError(f"MCP config path must not contain '..': {path}")


def resolve_mcp_config_path(config: Config | None = None) -> Path:
    """Resolved MCP config path from ``Config`` or ``~/.deepseek/mcp.json``."""
    if config is not None and config.mcp_config_path is not None:
        return config.mcp_config_path.expanduser()
    from deepseek_tui.config.paths import user_mcp_config_path

    return user_mcp_config_path()


def load_raw_document(path: Path) -> dict[str, Any]:
    validate_mcp_config_path(path)
    if not path.exists():
        return {"servers": {}, "timeouts": dict(DEFAULT_TIMEOUTS)}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid MCP config document: {path}")
    return data


def _servers_table(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    servers = doc.get("servers", doc.get("mcpServers"))
    if not isinstance(servers, dict):
        servers = {}
        doc["servers"] = servers
    elif "servers" not in doc:
        doc["servers"] = servers
    return servers


def save_document(path: Path, doc: dict[str, Any]) -> None:
    validate_mcp_config_path(path)
    write_json_atomic(path, doc)


def init_config(path: Path, *, force: bool = False) -> McpWriteStatus:
    if path.exists() and not force:
        return McpWriteStatus.SKIPPED_EXISTS
    status = McpWriteStatus.OVERWRITTEN if path.exists() else McpWriteStatus.CREATED
    doc = {
        "servers": {
            "example": {
                "command": "node",
                "args": ["./path/to/your-mcp-server.js"],
                "enabled": True,
                "disabled": True,
                "required": False,
            }
        },
        "timeouts": dict(DEFAULT_TIMEOUTS),
    }
    save_document(path, doc)
    return status


def add_server_config(
    path: Path,
    name: str,
    *,
    command: str | None = None,
    url: str | None = None,
    args: list[str] | None = None,
) -> None:
    if command is None and url is None:
        raise ValueError(f"Provide either a command or URL for MCP server '{name}'.")
    doc = load_raw_document(path)
    servers = _servers_table(doc)
    entry: dict[str, Any] = {"enabled": True, "required": False}
    if command is not None:
        entry["command"] = command
        entry["args"] = list(args or [])
    if url is not None:
        entry["url"] = url
    servers[name] = entry
    save_document(path, doc)


def remove_server_config(path: Path, name: str) -> None:
    doc = load_raw_document(path)
    servers = _servers_table(doc)
    if name not in servers:
        raise KeyError(f"MCP server '{name}' not found")
    del servers[name]
    save_document(path, doc)


def set_server_enabled(path: Path, name: str, enabled: bool) -> None:
    doc = load_raw_document(path)
    servers = _servers_table(doc)
    if name not in servers:
        raise KeyError(f"MCP server '{name}' not found")
    servers[name]["enabled"] = enabled
    servers[name]["disabled"] = not enabled
    save_document(path, doc)


def hash_mcp_document(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class McpDiscoveredItem:
    name: str
    model_name: str
    description: str = ""


@dataclass(slots=True)
class McpServerSnapshot:
    name: str
    enabled: bool
    required: bool
    transport: str
    command_or_url: str
    connected: bool = False
    error: str | None = None
    tools: list[McpDiscoveredItem] = field(default_factory=list)


@dataclass(slots=True)
class McpManagerSnapshot:
    config_path: Path
    config_exists: bool
    restart_required: bool
    servers: list[McpServerSnapshot]


def snapshot_from_configs(
    path: Path,
    configs: list[McpServerConfig],
    *,
    restart_required: bool = False,
    connection_errors: dict[str, str] | None = None,
    discovered_tools: dict[str, list[McpDiscoveredItem]] | None = None,
) -> McpManagerSnapshot:
    errors = connection_errors or {}
    tools_by_server = discovered_tools or {}
    servers: list[McpServerSnapshot] = []
    for cfg in sorted(configs, key=lambda c: c.name):
        transport = "http/sse" if cfg.url else "stdio"
        if cfg.url:
            command_or_url = cfg.url
        else:
            command_or_url = cfg.command or "(missing)"
            if cfg.args:
                command_or_url = f"{command_or_url} {' '.join(cfg.args)}"
        error = errors.get(cfg.name)
        if not cfg.enabled:
            error = error or "disabled"
        connected = cfg.enabled and cfg.name not in errors and cfg.name in tools_by_server
        servers.append(
            McpServerSnapshot(
                name=cfg.name,
                enabled=cfg.enabled,
                required=cfg.required,
                transport=transport,
                command_or_url=command_or_url,
                connected=connected,
                error=error,
                tools=tools_by_server.get(cfg.name, []),
            )
        )
    return McpManagerSnapshot(
        config_path=path,
        config_exists=path.exists(),
        restart_required=restart_required,
        servers=servers,
    )


def manager_snapshot_from_config(
    path: Path,
    *,
    restart_required: bool = False,
) -> McpManagerSnapshot:
    configs = load_mcp_config(path) if path.exists() else []
    return snapshot_from_configs(path, configs, restart_required=restart_required)


def format_manager_snapshot(snapshot: McpManagerSnapshot) -> str:
    lines = [
        f"MCP config: {snapshot.config_path}",
        f"Servers: {len(snapshot.servers)}",
    ]
    if snapshot.restart_required:
        lines.append(
            "Restart required — config changed; restart TUI to rebuild model-visible MCP tools."
        )
    if not snapshot.servers:
        lines.append("")
        lines.append("No MCP servers configured.")
        return "\n".join(lines)
    lines.append("")
    for server in snapshot.servers:
        status = "connected" if server.connected else "disconnected"
        if server.error:
            status = server.error
        req = " required" if server.required else ""
        lines.append(
            f"• {server.name} [{server.transport}] enabled={server.enabled}{req} — {status}"
        )
        lines.append(f"    {server.command_or_url}")
        if server.tools:
            lines.append(f"    tools ({len(server.tools)}):")
            for tool in server.tools[:8]:
                lines.append(f"      - {tool.name} → {tool.model_name}")
            if len(server.tools) > 8:
                lines.append(f"      ... +{len(server.tools) - 8} more")
    return "\n".join(lines)


async def discover_manager_snapshot(
    path: Path,
    *,
    restart_required: bool = False,
) -> McpManagerSnapshot:
    """Connect to enabled servers and build a live discovery snapshot."""
    from deepseek_tui.mcp.manager import McpManager

    configs = load_mcp_config(path) if path.exists() else []
    manager = McpManager(configs, config_path=path)
    errors: dict[str, str] = {}
    discovered: dict[str, list[McpDiscoveredItem]] = {}
    try:
        await manager.discover_tools()
        errors = manager.discover_errors
        discovered = {
            server: [
                McpDiscoveredItem(
                    name=item["name"],
                    model_name=item["model_name"],
                    description=item["description"],
                )
                for item in tools
            ]
            for server, tools in manager.grouped_discovered_tools().items()
        }
    finally:
        await manager.stop_all()
    return snapshot_from_configs(
        path,
        configs,
        restart_required=restart_required,
        connection_errors=errors,
        discovered_tools=discovered,
    )
