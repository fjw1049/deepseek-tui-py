"""Session-scoped runtime adapters owned by the plugin host."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any

from deepseek_tui.mcp.client import McpError, qualify_tool_name
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
        matches = [manager for manager in self._managers if server in manager.server_names]
        return matches[0] if len(matches) == 1 else None

    def _manager_for_tool(self, qualified: str) -> McpManager | None:
        matches = [manager for manager in self._managers
                   if manager._match_configured_server(qualified) is not None]
        return matches[0] if len(matches) == 1 else None

    def _unique_tools(self, groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        entries = [(manager, tool) for manager, group in zip(self._managers, groups) for tool in group]
        counts = Counter(tool["function"]["name"] for _, tool in entries)
        conflicts = {name for name, count in counts.items() if count > 1}
        if conflicts:
            logging.getLogger(__name__).warning("Conflicting MCP providers: %s", sorted(conflicts))
        return [tool for manager, tool in entries
                if counts[tool["function"]["name"]] == 1
                and self._manager_for_tool(tool["function"]["name"]) is manager]

    async def reload_if_config_changed(self) -> bool:
        changed = await asyncio.gather(*(m.reload_if_config_changed() for m in self._managers))
        return any(changed)

    def _match_configured_server(self, qualified: str) -> str | None:
        manager = self._manager_for_tool(qualified)
        return manager._match_configured_server(qualified) if manager else None

    def declared_capabilities(self, qualified_tool_name: str) -> list[str]:
        manager = self._manager_for_tool(qualified_tool_name)
        return manager.declared_capabilities(qualified_tool_name) if manager else []

    def is_server_running(self, name: str) -> bool:
        manager = self._manager_for_server(name)
        return manager.is_server_running(name) if manager else False

    def server_runtime_status(self, name: str) -> dict[str, Any]:
        manager = self._manager_for_server(name)
        if manager is None:
            return {"status": "disabled", "connected": False, "error": None}
        return manager.server_runtime_status(name)

    def cached_tools(self) -> list[dict[str, Any]] | None:
        caches = [manager.cached_tools() for manager in self._managers]
        if any(cache is None for cache in caches):
            return None
        return self._unique_tools([cache or [] for cache in caches])

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
            if self._manager_for_server(name) is manager
        }

    def tools_http_payload(self) -> list[dict[str, Any]]:
        return [tool for manager in self._managers for tool in manager.tools_http_payload()
                if self._manager_for_tool(qualify_tool_name(tool["server"], tool["name"])) is manager]

    def schedule_background_discover(self) -> None:
        for manager in self._managers:
            manager.schedule_background_discover()

    def server_config(self, name: str):  # type: ignore[override]
        manager = self._manager_for_server(name)
        return manager.server_config(name) if manager else None

    def is_on_focus_server(self, name: str) -> bool:
        manager = self._manager_for_server(name)
        return manager.is_on_focus_server(name) if manager else False

    def focus_api_tools(self, server: str) -> list[dict[str, Any]]:
        manager = self._manager_for_server(server)
        return [tool for tool in manager.focus_api_tools(server)
                if self._manager_for_tool(tool["function"]["name"]) is manager] if manager else []

    async def ensure_focus_server_discovered(self, name: str) -> list[dict[str, Any]]:
        await self.reload_if_config_changed()
        manager = self._manager_for_server(name)
        if manager is None:
            raise McpError(f"Unknown MCP server: {name}")
        tools = await manager.ensure_focus_server_discovered(name)
        return [tool for tool in tools if self._manager_for_tool(tool["function"]["name"]) is manager]

    async def release_focus_server(self, name: str) -> None:
        manager = self._manager_for_server(name)
        if manager is not None:
            await manager.release_focus_server(name)

    async def discover_tools(self) -> list[dict[str, Any]]:
        groups = await asyncio.gather(*(manager.discover_tools() for manager in self._managers))
        return self._unique_tools(groups)

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await self.reload_if_config_changed()
        manager = self._manager_for_tool(qualified_name)
        if manager is None:
            raise McpError(f"Unknown or ambiguous MCP tool provider: {qualified_name}")
        return await manager.call_tool(qualified_name, arguments)

    async def list_resources(self, server: str | None = None) -> dict[str, list[dict[str, Any]]]:
        await self.reload_if_config_changed()
        if server is not None:
            manager = self._manager_for_server(server)
            return await manager.list_resources(server) if manager else {}
        groups = await asyncio.gather(*(manager.list_resources() for manager in self._managers))
        return {name: items for manager, group in zip(self._managers, groups)
                for name, items in group.items() if self._manager_for_server(name) is manager}

    async def read_resource(self, server: str, uri: str) -> dict[str, Any]:
        await self.reload_if_config_changed()
        manager = self._manager_for_server(server)
        if manager is None:
            raise McpError(f"Unknown MCP server: {server}")
        return await manager.read_resource(server, uri)
