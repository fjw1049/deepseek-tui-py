from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.mcp.config import McpServerConfig


class McpError(Exception):
    """Error from an MCP server."""


@dataclass(slots=True)
class McpToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class McpClient:
    """Stdio JSON-RPC client for a single MCP server."""

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._initialized = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        if self.config.url is not None:
            raise McpError("HTTP MCP transport is not implemented yet")
        if self.config.command is None:
            raise McpError("MCP stdio server requires a command")
        env = {**os.environ, **self.config.env}
        self._process = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        await self._initialize()

    async def stop(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            self._process.kill()
        self._process = None
        self._initialized = False

    async def list_tools(self) -> list[McpToolDescriptor]:
        result = await self._send_request("tools/list", {})
        tools_raw = result.get("tools", [])
        descriptors: list[McpToolDescriptor] = []
        for t in tools_raw:
            if not isinstance(t, dict):
                continue
            descriptors.append(
                McpToolDescriptor(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                )
            )
        return descriptors

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._send_request("tools/call", {"name": name, "arguments": arguments})
        return result

    async def list_resources(self) -> list[dict[str, Any]]:
        result = await self._send_request("resources/list", {})
        resources = result.get("resources", [])
        return [item for item in resources if isinstance(item, dict)]

    async def list_resource_templates(self) -> list[dict[str, Any]]:
        result = await self._send_request("resources/templates/list", {})
        templates = result.get("resourceTemplates", [])
        return [item for item in templates if isinstance(item, dict)]

    async def read_resource(self, uri: str) -> dict[str, Any]:
        return await self._send_request("resources/read", {"uri": uri})

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._send_request("prompts/get", {"name": name, "arguments": arguments or {}})

    async def _initialize(self) -> None:
        await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "deepseek-tui-py",
                    "version": "0.1.0",
                },
            },
        )
        await self._send_notification("notifications/initialized", {})
        self._initialized = True

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None:
            raise McpError("MCP client not started")
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        line = json.dumps(request) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()
        response = await self._read_response()
        if "error" in response:
            err = response["error"]
            msg = err.get("message", "unknown error") if isinstance(err, dict) else str(err)
            raise McpError(f"MCP error: {msg}")
        result: dict[str, Any] = response.get("result", {})
        return result

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise McpError("MCP client not started")
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        line = json.dumps(notification) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_response(self) -> dict[str, Any]:
        if self._process is None or self._process.stdout is None:
            raise McpError("MCP client not started")
        while True:
            raw = await self._process.stdout.readline()
            if not raw:
                raise McpError("MCP server closed stdout")
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            data = json.loads(line)
            if "id" in data:
                result: dict[str, Any] = data
                return result
