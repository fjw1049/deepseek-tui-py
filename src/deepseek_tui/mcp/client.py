"""MCP client — transport-agnostic JSON-RPC 2.0 wrapper.

Speaks stdio or SSE/HTTP depending on ``McpServerConfig.url``; the
transport is picked in :meth:`McpClient.start` via :func:`build_transport`.
"""

from __future__ import annotations



import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.transport import (
    McpTransport,
    McpTransportError,
    SseTransport,
    StdioTransport,
    StreamableHttpTransport,
)


# --- tool name encoding -----------------------------------------------------


def qualify_tool_name(server_name: str, tool_name: str) -> str:
    """Encode an MCP tool name as ``mcp_<server>_<tool>``."""
    sanitized_server = re.sub(r"[^a-z0-9_]", "_", server_name.lower())
    sanitized_tool = re.sub(r"[^a-z0-9_]", "_", tool_name.lower())
    qualified = f"mcp_{sanitized_server}_{sanitized_tool}"
    if len(qualified) > 64:
        hash_suffix = hashlib.sha256(qualified.encode()).hexdigest()[:12]
        qualified = qualified[:51] + "_" + hash_suffix
    return qualified


def parse_qualified_tool_name(qualified: str) -> tuple[str, str] | None:
    """Parse a qualified MCP tool name back into ``(server, tool)``.

    Best-effort fallback only: the ``mcp_<server>_<tool>`` encoding is
    ambiguous when the server name itself contains underscores (e.g.
    ``mcp_my_server_do_thing`` parses as ``("my", "server_do_thing")``).
    Callers that know the real mapping (e.g. ``McpManager``'s tool-map
    cache, which stores the ``(server, tool)`` pair explicitly) should
    prefer it over this parser.
    """
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

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def is_method_not_found(exc: BaseException) -> bool:
    """True for JSON-RPC -32601 / "Method not found" (optional capability absent)."""
    if isinstance(exc, McpError) and exc.code == -32601:
        return True
    return "method not found" in str(exc).lower()


@dataclass(slots=True)
class McpToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


def build_transport(config: McpServerConfig) -> McpTransport:
    """Pick stdio / SSE / Streamable HTTP from the config shape."""
    if config.url is not None:
        headers = dict(config.headers)
        hint = (config.transport or "").strip().lower()
        if hint in {"streamablehttp", "http"}:
            return StreamableHttpTransport(
                url=config.url,
                headers=headers,
                connect_timeout=config.connect_timeout,
            )
        return SseTransport(
            url=config.url,
            headers=headers,
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
        # Server capabilities from initialize; None until handshake succeeds.
        self._server_capabilities: dict[str, Any] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False

    def supports_capability(self, name: str) -> bool | None:
        """Whether the server declared ``name`` in initialize capabilities.

        Returns ``None`` when capabilities are unknown (not yet initialized).
        """
        if self._server_capabilities is None:
            return None
        return name in self._server_capabilities

    def _mark_dead(self, exc: BaseException | None = None) -> None:
        """Mark this client unusable after reader/transport failure.

        Sets ``_closed`` so ``is_running`` becomes False while leaving
        ``_transport`` for ``stop()`` / ``_ensure_client`` to tear down
        (stdio child process, SSE client, etc.).
        """
        self._closed = True
        self._initialized = False
        self._server_capabilities = None
        err = McpError(
            f"MCP transport closed: {exc}" if exc is not None else "MCP client dead"
        )
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()

    @property
    def is_running(self) -> bool:
        """True only while transport + reader are alive and not closed.

        After a transport/reader failure we mark the client dead so
        ``McpManager._ensure_client`` rebuilds instead of reusing a zombie.
        """
        if self._closed or self._transport is None:
            return False
        reader = self._reader_task
        if reader is None or reader.done():
            return False
        return True

    async def start(self) -> None:
        if self.is_running:
            return
        # Tear down any leftover transport/reader from a previous death so a
        # direct restart (not only manager replacement) does not leak children.
        if self._transport is not None or self._reader_task is not None:
            await self.stop()
        self._closed = False
        self._initialized = False
        self._server_capabilities = None
        self._pending.clear()
        transport = build_transport(self.config)
        try:
            await transport.start()
        except McpTransportError as exc:
            raise McpError(str(exc)) from exc
        self._transport = transport
        self._reader_task = asyncio.create_task(self._reader_loop())
        try:
            await self._initialize()
        except BaseException:
            await self.stop()
            raise

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
        self._server_capabilities = None

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
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=self.config.execute_timeout,
        )

    async def list_resources(self) -> list[dict[str, Any]]:
        if self.supports_capability("resources") is False:
            return []
        try:
            result = await self._send_request("resources/list", {})
        except McpError as exc:
            if is_method_not_found(exc):
                return []
            raise
        resources = result.get("resources", [])
        return [item for item in resources if isinstance(item, dict)]

    async def read_resource(self, uri: str) -> dict[str, Any]:
        if self.supports_capability("resources") is False:
            raise McpError(
                f"MCP server {self.config.name!r} does not support resources "
                f"(no capabilities.resources in initialize)"
            )
        try:
            return await self._send_request("resources/read", {"uri": uri})
        except McpError as exc:
            if is_method_not_found(exc):
                raise McpError(
                    f"MCP server {self.config.name!r} does not support resources/read",
                    code=exc.code,
                ) from exc
            raise

    # --- internal -------------------------------------------------------

    async def _initialize(self) -> None:
        result = await self._send_request(
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
        caps = result.get("capabilities") if isinstance(result, dict) else None
        self._server_capabilities = caps if isinstance(caps, dict) else {}
        await self._send_notification("notifications/initialized", {})
        self._initialized = True

    async def _reader_loop(self) -> None:
        assert self._transport is not None
        try:
            while not self._closed:
                message = await self._transport.recv()
                msg_id = message.get("id")
                if msg_id is None:
                    # Server notification — ignore for now
                    continue
                fut = self._pending.pop(msg_id, None)
                if fut is not None and not fut.done():
                    fut.set_result(message)
        except asyncio.CancelledError:
            pass
        except McpTransportError as exc:
            # Transport gone — fail waiters and mark dead so the manager
            # rebuilds on the next call instead of reusing a zombie.
            self._mark_dead(exc)
        except Exception as exc:  # noqa: BLE001
            self._mark_dead(exc)

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
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
            effective_timeout = (
                timeout if timeout is not None else self.config.read_timeout
            )
            response = await asyncio.wait_for(fut, timeout=effective_timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise McpError(
                f"MCP request {method} timed out after {effective_timeout}s"
            ) from exc

        if "error" in response:
            err = response["error"]
            if isinstance(err, dict):
                msg = err.get("message", "unknown error")
                raw_code = err.get("code")
                code = raw_code if isinstance(raw_code, int) else None
            else:
                msg = str(err)
                code = None
            raise McpError(f"MCP error: {msg}", code=code)
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

