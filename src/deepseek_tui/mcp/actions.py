"""Shared MCP config actions for CLI and TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from deepseek_tui.mcp.store import (
    McpWriteStatus,
    add_server_config,
    format_manager_snapshot,
    init_config,
    manager_snapshot_from_config,
    remove_server_config,
    set_server_enabled,
)

ADD_USAGE = (
    "Usage: /mcp add stdio <name> <command> [args...] "
    "OR /mcp add http <name> <url>"
)


@dataclass(frozen=True)
class McpMutationResult:
    message: str
    output: str


def format_status(path: Path, *, restart_required: bool = False) -> str:
    snapshot = manager_snapshot_from_config(
        path, restart_required=restart_required
    )
    return format_manager_snapshot(snapshot)


def run_init(path: Path, *, force: bool = False) -> McpMutationResult:
    status = init_config(path, force=force)
    if status == McpWriteStatus.CREATED:
        message = f"Created MCP config at {path}"
    elif status == McpWriteStatus.OVERWRITTEN:
        message = f"Overwrote MCP config at {path}"
    else:
        message = (
            f"MCP config already exists at {path} "
            f"(use /mcp init --force to overwrite)"
        )
    snapshot = manager_snapshot_from_config(path, restart_required=False)
    return McpMutationResult(
        message=message,
        output=f"{message}\n\n{format_manager_snapshot(snapshot)}",
    )


def run_add(
    path: Path,
    transport: str,
    rest: list[str],
    *,
    restart_required: bool,
) -> McpMutationResult:
    if len(rest) < 3:
        raise ValueError(ADD_USAGE)
    transport = transport.lower()
    if transport == "stdio":
        name, command, *cmd_args = rest[1], rest[2], rest[3:]
        add_server_config(path, name, command=command, args=cmd_args)
        message = f"Added MCP stdio server '{name}'"
    elif transport in {"http", "sse"}:
        name, url = rest[1], rest[2]
        add_server_config(path, name, url=url)
        message = f"Added MCP HTTP/SSE server '{name}'"
    else:
        raise ValueError(ADD_USAGE)
    snapshot = manager_snapshot_from_config(
        path, restart_required=restart_required
    )
    return McpMutationResult(
        message=message,
        output=f"{message}\n\n{format_manager_snapshot(snapshot)}",
    )


def run_enable(path: Path, name: str, *, restart_required: bool) -> McpMutationResult:
    set_server_enabled(path, name, True)
    message = f"Enabled MCP server '{name}'"
    return _mutation_with_snapshot(path, message, restart_required=restart_required)


def run_disable(path: Path, name: str, *, restart_required: bool) -> McpMutationResult:
    set_server_enabled(path, name, False)
    message = f"Disabled MCP server '{name}'"
    return _mutation_with_snapshot(path, message, restart_required=restart_required)


def run_remove(path: Path, name: str, *, restart_required: bool) -> McpMutationResult:
    remove_server_config(path, name)
    message = f"Removed MCP server '{name}'"
    return _mutation_with_snapshot(path, message, restart_required=restart_required)


def _mutation_with_snapshot(
    path: Path,
    message: str,
    *,
    restart_required: bool,
) -> McpMutationResult:
    snapshot = manager_snapshot_from_config(
        path, restart_required=restart_required
    )
    return McpMutationResult(
        message=message,
        output=f"{message}\n\n{format_manager_snapshot(snapshot)}",
    )
