"""MCP capability adapter for host runtime assembly."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from deepseek_tui.config.models import Config
from deepseek_tui.host.services import ServiceRegistry, ServiceScope
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.tools.base import ToolError, ToolResult
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.mcp_tools import MCP_MANAGER_KEY

logger = logging.getLogger(__name__)

MCP_PRELOAD_DISABLED_STATUS: dict[str, Any] = {
    "phase": "disabled",
    "warming": False,
    "ready": True,
    "enabled_servers": 0,
    "connected_servers": 0,
    "tools_count": 0,
    "from_disk_cache": False,
    "started_at_ms": None,
    "completed_at_ms": None,
    "error": None,
}


async def create_mcp_manager(
    config: Config,
    services: ServiceRegistry,
    *,
    provided_manager: McpManager | None,
    start_mcp: bool,
) -> tuple[McpManager | None, bool]:
    owns_manager = True
    if provided_manager is not None:
        manager = provided_manager
        owns_manager = False
    elif config.features.mcp:
        manager = await _build_mcp_manager(config)
    else:
        manager = None

    if manager is not None:
        services.add(McpManager, manager, owner="mcp", scope=ServiceScope.PROCESS)
        if start_mcp:
            await manager.start_all(fail_on_required=True)
    return manager, owns_manager


def attach_mcp_bindings(
    manager: McpManager | None,
    *,
    services: ServiceRegistry,
) -> None:
    if manager is None:
        return
    if services.optional_named(MCP_MANAGER_KEY) is None:
        services.add_named(MCP_MANAGER_KEY, manager, owner="mcp", scope=ServiceScope.PROCESS)


def mcp_manager_from_runtime_or_context(
    *,
    tool_runtime: object | None,
    context: ToolContext,
) -> McpManager | None:
    if tool_runtime is not None:
        runtime_manager = getattr(tool_runtime, "mcp_manager", None)
        if isinstance(runtime_manager, McpManager):
            return runtime_manager
    manager = context.services.optional(McpManager)
    if manager is not None:
        return manager
    raw = context.services.optional_named(MCP_MANAGER_KEY)
    if isinstance(raw, McpManager):
        return raw
    return None


def build_mcp_augmented_tool_catalog(
    *,
    native_tools: list[dict[str, Any]],
    mcp_manager: McpManager | None,
    cached_tools: list[dict[str, Any]] | None,
    mode: str,
    profile: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    from deepseek_tui.engine.tool_catalog import build_model_tool_catalog
    from deepseek_tui.engine.tool_profiles import filter_tools_for_profile

    if mcp_manager is None:
        return filter_tools_for_profile(list(native_tools), profile), cached_tools

    mcp_tools = cached_tools
    if mcp_tools is None:
        mcp_tools = mcp_manager.cached_tools()
    if mcp_tools is None:
        # Never block a user turn on cold MCP subprocess startup.
        mcp_manager.schedule_background_discover()
        logger.info("mcp_discover_deferred native_tools=%d", len(native_tools))
        return filter_tools_for_profile(list(native_tools), profile), cached_tools
    if not mcp_tools:
        return filter_tools_for_profile(list(native_tools), profile), cached_tools

    new_cache = list(mcp_tools)
    combined = build_model_tool_catalog(list(native_tools), new_cache, mode)
    return filter_tools_for_profile(combined, profile), new_cache


def is_external_mcp_tool_call(tool_name: str, *, registry_contains: bool) -> bool:
    from deepseek_tui.mcp.execute import is_external_mcp_tool

    return bool(is_external_mcp_tool(tool_name, registry_contains))


async def execute_mcp_tool(
    manager: McpManager | None,
    tool_name: str,
    arguments: dict[str, Any],
) -> ToolResult:
    if manager is None:
        raise ToolError(f"MCP tool '{tool_name}' called but no MCP manager configured")
    from deepseek_tui.mcp.execute import execute_external_mcp_tool

    return await execute_external_mcp_tool(manager, tool_name, arguments)


def normalize_mcp_tool_name(tool_name: str) -> str:
    from deepseek_tui.mcp.execute import normalize_mcp_bridge_tool_name

    return str(normalize_mcp_bridge_tool_name(tool_name))


async def try_execute_external_mcp_tool(
    *,
    manager: McpManager | None,
    tool_name: str,
    arguments: dict[str, Any],
    registry_contains: bool,
) -> ToolResult | None:
    normalized = normalize_mcp_tool_name(tool_name)
    if not is_external_mcp_tool_call(normalized, registry_contains=registry_contains):
        return None
    return await execute_mcp_tool(manager, normalized, arguments)


def schedule_mcp_preload_for_tool_runtime(
    *,
    mcp_enabled: bool,
    tool_runtime: object | None,
) -> None:
    if not mcp_enabled or tool_runtime is None:
        return
    manager = getattr(tool_runtime, "mcp_manager", None)
    if manager is None:
        return
    manager.schedule_startup_preload()


def mcp_preload_status_for_tool_runtime(
    *,
    mcp_enabled: bool,
    tool_runtime: object | None,
) -> dict[str, Any]:
    if not mcp_enabled:
        return dict(MCP_PRELOAD_DISABLED_STATUS)
    if tool_runtime is None:
        return {"phase": "idle", "warming": False, "ready": False}
    manager = getattr(tool_runtime, "mcp_manager", None)
    if manager is None:
        return {"phase": "disabled", "warming": False, "ready": True}
    return cast(dict[str, Any], manager.preload_status())


def contribute_runtime_surfaces(registry: object) -> None:
    from deepseek_tui.app_server.runtime_api.routes.mcp import (
        mcp_preload_status,
        mcp_startup,
    )

    registry.add_route(  # type: ignore[attr-defined]
        id="mcp.startup",
        owner="mcp",
        method="POST",
        path="/v1/mcp/startup",
        handler=mcp_startup,
    )
    registry.add_route(  # type: ignore[attr-defined]
        id="mcp.preload_status",
        owner="mcp",
        method="GET",
        path="/v1/mcp/preload-status",
        handler=mcp_preload_status,
    )


async def mcp_startup_response(request: object) -> dict[str, Any]:
    from deepseek_tui.app_server.runtime_api.runtime_delegate import runtime_from_request

    return await mcp_startup_runtime_response(runtime_from_request(request))


def mcp_preload_status_response(request: object) -> dict[str, Any]:
    from deepseek_tui.app_server.runtime_api.runtime_delegate import runtime_from_request

    return mcp_preload_status_runtime_response(runtime_from_request(request))


async def mcp_startup_runtime_response(runtime: object) -> dict[str, Any]:
    return cast(dict[str, Any], await runtime.mcp_startup())  # type: ignore[attr-defined]


def mcp_preload_status_runtime_response(runtime: object) -> dict[str, Any]:
    return cast(dict[str, Any], runtime.mcp_preload_status())  # type: ignore[attr-defined]


async def mcp_servers_runtime_response(runtime: object) -> dict[str, Any]:
    return cast(dict[str, Any], await runtime.list_mcp_servers())  # type: ignore[attr-defined]


async def mcp_tools_runtime_response(runtime: object) -> dict[str, Any]:
    return cast(dict[str, Any], await runtime.list_mcp_tools())  # type: ignore[attr-defined]


async def shutdown_mcp_manager(
    manager: McpManager | None,
    *,
    owns_manager: bool,
) -> None:
    if owns_manager and manager is not None:
        await manager.stop_all()


async def _build_mcp_manager(config: Config) -> McpManager:
    from deepseek_tui.mcp.config import load_mcp_config

    path = config.mcp_config_path.expanduser()
    try:
        servers = load_mcp_config(path)
    except (OSError, ValueError):
        servers = []
    return McpManager(servers, config_path=Path(path))
