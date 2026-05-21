"""MCP startup summary helpers.

Mirrors ``crates/mcp/src/lib.rs`` ``McpManager::start_all`` and
``crates/tui/src/mcp.rs`` required-server validation (mcp.rs:1594-1607).
"""

from __future__ import annotations

from collections.abc import Callable

from deepseek_tui.mcp.client import McpError
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.protocol.mcp_lifecycle import (
    McpStartupCompleteEvent,
    McpStartupFailure,
    McpStartupStatus,
    McpStartupUpdateEvent,
)

StartupUpdateCallback = Callable[[McpStartupUpdateEvent], None]


def required_startup_failures(
    configs: dict[str, McpServerConfig],
    summary: McpStartupCompleteEvent,
) -> list[McpStartupFailure]:
    """Return failures for enabled ``required`` servers that did not become ready."""
    ready = set(summary.ready)
    out: list[McpStartupFailure] = []
    seen = {f.server_name for f in summary.failed}
    for name, cfg in configs.items():
        if not cfg.enabled or not cfg.required:
            continue
        if name in ready:
            continue
        existing = next((f for f in summary.failed if f.server_name == name), None)
        if existing is not None:
            out.append(existing)
        elif name not in seen:
            out.append(
                McpStartupFailure(
                    server_name=name,
                    error="required MCP server failed to initialize",
                )
            )
    return out


def raise_if_required_mcp_failed(
    configs: dict[str, McpServerConfig],
    summary: McpStartupCompleteEvent,
) -> None:
    """Raise :class:`McpError` when any required server failed startup."""
    failures = required_startup_failures(configs, summary)
    if not failures:
        return
    detail = "; ".join(f"{f.server_name}: {f.error}" for f in failures)
    raise McpError(f"Required MCP server(s) failed to start: {detail}")
