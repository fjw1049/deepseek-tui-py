"""Session-scoped runtime adapters owned by the plugin host."""

from __future__ import annotations

import asyncio
from typing import Any

from deepseek_tui.mcp.client import McpError
from deepseek_tui.mcp.manager import McpManager


class CompositeMcpManager(McpManager):
    """Read/write view over independent MCP managers.

    The process runtime keeps its base manager while each plugin session owns
    a separate manager.  This adapter gives Engine one familiar interface
    without mutating shared state or leaking providers across workspaces.
    """

    def __init__(self, *managers: McpManager | None) -> None:
        super().__init__([])
        self._managers = tuple(manager for manager in managers if manager is not None)

    @property
    def server_names(self) -> list[str]:
        return list(
            dict.fromkeys(name for manager in self._managers for name in manager.server_names)
        )

    def _manager_for_server(self, server: str) -> McpManager | None:
        return next(
            (manager for manager in self._managers if server in manager.server_names),
            None,
        )

    def _manager_for_tool(self, qualified: str) -> McpManager | None:
        return next(
            (
                manager
                for manager in self._managers
                if manager._match_configured_server(qualified) is not None
            ),
            None,
        )

    def _match_configured_server(self, qualified: str) -> str | None:
        manager = self._manager_for_tool(qualified)
        return manager._match_configured_server(qualified) if manager else None

    def declared_capabilities(self, qualified_tool_name: str) -> list[str]:
        manager = self._manager_for_tool(qualified_tool_name)
        return manager.declared_capabilities(qualified_tool_name) if manager else []

    def is_server_running(self, name: str) -> bool:
        manager = self._manager_for_server(name)
        return manager.is_server_running(name) if manager else False

    def cached_tools(self) -> list[dict[str, Any]] | None:
        caches = [manager.cached_tools() for manager in self._managers]
        if any(cache is None for cache in caches):
            return None
        return [tool for cache in caches for tool in (cache or [])]

    @property
    def discover_errors(self) -> dict[str, str]:
        return {
            name: error
            for manager in self._managers
            for name, error in manager.discover_errors.items()
        }

    def grouped_discovered_tools(self) -> dict[str, list[dict[str, str]]]:
        return {
            name: tools
            for manager in self._managers
            for name, tools in manager.grouped_discovered_tools().items()
        }

    def tools_http_payload(self) -> list[dict[str, Any]]:
        return [tool for manager in self._managers for tool in manager.tools_http_payload()]

    def schedule_background_discover(self) -> None:
        for manager in self._managers:
            manager.schedule_background_discover()

    async def discover_tools(self) -> list[dict[str, Any]]:
        groups = await asyncio.gather(*(manager.discover_tools() for manager in self._managers))
        return [tool for group in groups for tool in group]

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        manager = self._manager_for_tool(qualified_name)
        if manager is None:
            raise McpError(f"Not an MCP tool: {qualified_name}")
        return await manager.call_tool(qualified_name, arguments)

    async def list_resources(self, server: str | None = None) -> dict[str, list[dict[str, Any]]]:
        if server is not None:
            manager = self._manager_for_server(server)
            return await manager.list_resources(server) if manager else {}
        groups = await asyncio.gather(*(manager.list_resources() for manager in self._managers))
        return {name: items for group in groups for name, items in group.items()}

    async def list_resource_templates(
        self, server: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        if server is not None:
            manager = self._manager_for_server(server)
            return await manager.list_resource_templates(server) if manager else {}
        groups = await asyncio.gather(
            *(manager.list_resource_templates() for manager in self._managers)
        )
        return {name: items for group in groups for name, items in group.items()}

    async def read_resource(self, server: str, uri: str) -> dict[str, Any]:
        manager = self._manager_for_server(server)
        if manager is None:
            raise McpError(f"Unknown MCP server: {server}")
        return await manager.read_resource(server, uri)

    async def get_prompt(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manager = self._manager_for_server(server)
        if manager is None:
            raise McpError(f"Unknown MCP server: {server}")
        return await manager.get_prompt(server, name, arguments)
