from __future__ import annotations

from typing import Any

from deepseek_tui.mcp.client import McpClient, McpError
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.encoding import parse_qualified_tool_name, qualify_tool_name


class McpManager:
    """Manages multiple MCP server connections and tool routing."""

    def __init__(self, configs: list[McpServerConfig] | None = None) -> None:
        self._configs: dict[str, McpServerConfig] = {}
        self._clients: dict[str, McpClient] = {}
        self._tool_map: dict[str, tuple[str, str]] = {}
        if configs:
            for cfg in configs:
                self._configs[cfg.name] = cfg

    @property
    def server_names(self) -> list[str]:
        return list(self._configs.keys())

    async def start_all(self) -> None:
        for name, cfg in self._configs.items():
            if not cfg.enabled:
                continue
            await self._ensure_client(name)

    async def stop_all(self) -> None:
        for client in self._clients.values():
            await client.stop()
        self._clients.clear()
        self._tool_map.clear()

    async def discover_tools(self) -> list[dict[str, Any]]:
        """Discover tools from all running servers, returns API-format list."""
        api_tools: list[dict[str, Any]] = []
        self._tool_map.clear()
        for server_name, client in self._clients.items():
            cfg = self._configs[server_name]
            try:
                descriptors = await client.list_tools()
            except McpError:
                continue
            for desc in descriptors:
                if cfg.tool_filter and not cfg.tool_filter.accepts(desc.name):
                    continue
                qualified = qualify_tool_name(server_name, desc.name)
                self._tool_map[qualified] = (server_name, desc.name)
                api_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": qualified,
                            "description": desc.description,
                            "parameters": desc.input_schema,
                        },
                    }
                )
        return sorted(api_tools, key=lambda t: t["function"]["name"])

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        mapping = self._tool_map.get(qualified_name)
        if mapping is None:
            parsed = parse_qualified_tool_name(qualified_name)
            if parsed is None:
                raise McpError(f"Not an MCP tool: {qualified_name}")
            mapping = parsed
        server_name, tool_name = mapping
        client = await self._ensure_client(server_name)
        return await client.call_tool(tool_name, arguments)

    async def list_resources(self, server: str | None = None) -> dict[str, list[dict[str, Any]]]:
        return await self._collect(server, "list_resources")

    async def list_resource_templates(
        self,
        server: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return await self._collect(server, "list_resource_templates")

    async def read_resource(self, server: str, uri: str) -> dict[str, Any]:
        client = await self._ensure_client(server)
        return await client.read_resource(uri)

    async def get_prompt(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._ensure_client(server)
        return await client.get_prompt(name, arguments)

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._tool_map or parse_qualified_tool_name(name) is not None

    async def _ensure_client(self, server_name: str) -> McpClient:
        if server_name in self._clients:
            client = self._clients[server_name]
            if client.is_running:
                return client
        cfg = self._configs.get(server_name)
        if cfg is None:
            raise McpError(f"Unknown MCP server: {server_name}")
        client = McpClient(cfg)
        await client.start()
        self._clients[server_name] = client
        return client

    async def _collect(
        self,
        server: str | None,
        method_name: str,
    ) -> dict[str, list[dict[str, Any]]]:
        names = [server] if server is not None else list(self._configs)
        output: dict[str, list[dict[str, Any]]] = {}
        for name in names:
            client = await self._ensure_client(name)
            method = getattr(client, method_name)
            output[name] = await method()
        return output
