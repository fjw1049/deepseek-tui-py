"""MCP client — transport-agnostic JSON-RPC 2.0 wrapper.

Mirrors ``crates/tui/src/mcp.rs:477-914`` (McpConnection). Speaks stdio
or SSE/HTTP depending on ``McpServerConfig.url``; the transport is
picked in :meth:`McpClient.start` via :func:`build_transport`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.transport import (
    McpTransport,
    McpTransportError,
    SseTransport,
    StdioTransport,
)


# --- tool name encoding -----------------------------------------------------


def qualify_tool_name(server_name: str, tool_name: str) -> str:
    """Encode an MCP tool name as ``mcp_<server>_<tool>`` (Rust TUI parity)."""
    sanitized_server = re.sub(r"[^a-z0-9_]", "_", server_name.lower())
    sanitized_tool = re.sub(r"[^a-z0-9_]", "_", tool_name.lower())
    qualified = f"mcp_{sanitized_server}_{sanitized_tool}"
    if len(qualified) > 64:
        hash_suffix = hashlib.sha256(qualified.encode()).hexdigest()[:12]
        qualified = qualified[:51] + "_" + hash_suffix
    return qualified


def parse_qualified_tool_name(qualified: str) -> tuple[str, str] | None:
    """Parse a qualified MCP tool name back into ``(server, tool)``."""
    if qualified.startswith("mcp__"):
        rest = qualified[5:]
        parts = rest.split("__", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
    if not qualified.startswith("mcp_"):
        return None
    rest = qualified[4:]
    if "_" not in rest:
        return None
    server, tool = rest.split("_", 1)
    if not server or not tool:
        return None
    return server, tool


class McpError(Exception):
    """Error from an MCP server."""


@dataclass(slots=True)
class McpToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


def build_transport(config: McpServerConfig) -> McpTransport:
    """Pick stdio vs SSE transport from the config shape.

    Mirrors Rust ``McpConnection::new`` (mcp.rs:485+).
    """
    if config.url is not None:
        return SseTransport(
            url=config.url,
            connect_timeout=config.connect_timeout,
        )
    if config.command is None:
        raise McpError(
            f"MCP server {config.name!r} has neither 'url' nor 'command'"
        )
    return StdioTransport(
        command=config.command,
        args=list(config.args),
        env=dict(config.env),
    )


class McpClient:
    """JSON-RPC 2.0 client for a single MCP server.

    Uses either stdio or SSE/HTTP transport. Outgoing requests are
    numbered and matched to incoming responses via a pending-id map so
    concurrent requests don't interleave.
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._transport: McpTransport | None = None
        self._request_id = 0
        self._initialized = False
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def is_running(self) -> bool:
        return self._transport is not None and not self._closed

    async def start(self) -> None:
        if self._transport is not None:
            return
        transport = build_transport(self.config)
        await transport.start()
        self._transport = transport
        self._reader_task = asyncio.create_task(self._reader_loop())
        await self._initialize()

    async def stop(self) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reader_task = None
        if self._transport is not None:
            try:
                await self._transport.stop()
            except Exception:  # noqa: BLE001
                pass
            self._transport = None
        # Fail any in-flight requests
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(McpError("MCP client stopped"))
        self._pending.clear()
        self._initialized = False

    # --- high-level RPC methods ------------------------------------------

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

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._send_request(
            "tools/call", {"name": name, "arguments": arguments}
        )

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
        return await self._send_request(
            "prompts/get", {"name": name, "arguments": arguments or {}}
        )

    # --- internal -------------------------------------------------------

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

    async def _reader_loop(self) -> None:
        assert self._transport is not None
        try:
            while not self._closed:
                message = await self._transport.recv()
                msg_id = message.get("id")
                if msg_id is None:
                    # Server notification — ignore for now (Rust logs them)
                    continue
                fut = self._pending.pop(msg_id, None)
                if fut is not None and not fut.done():
                    fut.set_result(message)
        except (McpTransportError, asyncio.CancelledError):
            pass
        except Exception as exc:  # noqa: BLE001
            # Propagate to any waiters so they unblock.
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(McpError(f"MCP reader died: {exc}"))
            self._pending.clear()

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if self._transport is None:
            raise McpError("MCP client not started")
        self._request_id += 1
        req_id = self._request_id
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = fut
        try:
            await self._transport.send(request)
        except McpTransportError as exc:
            self._pending.pop(req_id, None)
            raise McpError(str(exc)) from exc

        try:
            timeout = self.config.read_timeout
            response = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise McpError(
                f"MCP request {method} timed out after {self.config.read_timeout}s"
            ) from exc

        if "error" in response:
            err = response["error"]
            msg = err.get("message", "unknown error") if isinstance(err, dict) else str(err)
            raise McpError(f"MCP error: {msg}")
        result: dict[str, Any] = response.get("result", {})
        return result

    async def _send_notification(
        self, method: str, params: dict[str, Any]
    ) -> None:
        if self._transport is None:
            raise McpError("MCP client not started")
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            await self._transport.send(notification)
        except McpTransportError as exc:
            raise McpError(str(exc)) from exc

