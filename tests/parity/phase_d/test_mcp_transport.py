"""Parity tests for MCP transport + client + AppRuntime integration (Stage 4.3).

Mirror of Rust ``crates/tui/src/mcp.rs:260-472`` (McpTransport) and
``crates/mcp/src/lib.rs`` (McpManager). Covers:

- StdioTransport over a simple ``cat``-based echo child
- SseTransport endpoint discovery from ``event: endpoint``
- SseTransport message stream from ``event: message``
- SseTransport.send POSTs to discovered endpoint
- McpClient request/response pairing via a fake transport
- AppRuntime.mcp_startup returns per-server status when MCP is wired

httpx MockTransport drives the SSE server in-process so no sockets open.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio

from deepseek_tui.app_server import AppRuntime
from deepseek_tui.config.models import Config
from deepseek_tui.mcp.client import McpClient, McpError
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.mcp.transport import (
    McpTransport,
    McpTransportError,
    SseTransport,
    StdioTransport,
)

# --- StdioTransport -------------------------------------------------------


class TestStdioTransport:
    async def test_roundtrip_through_cat(self) -> None:
        """``cat`` echoes each line back — send/recv should round-trip."""
        transport = StdioTransport("cat")
        await transport.start()
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
            await transport.send(payload)
            got = await transport.recv()
            assert got == payload
        finally:
            await transport.stop()

    async def test_recv_fails_before_start(self) -> None:
        transport = StdioTransport("cat")
        with pytest.raises(McpTransportError):
            await transport.recv()


# --- SseTransport (in-proc via httpx MockTransport) -----------------------


class _SseServer:
    """Scripts an MCP SSE server response for in-process testing.

    Drives both the GET (SSE) and POST (endpoint) responses.
    """

    def __init__(self, endpoint_path: str = "/rpc") -> None:
        self.endpoint_path = endpoint_path
        self.posted: list[dict[str, Any]] = []

    def sse_body(self, responses: list[dict[str, Any]]) -> bytes:
        lines: list[str] = [
            f"event: endpoint\ndata: {self.endpoint_path}\n\n",
        ]
        for resp in responses:
            lines.append(f"event: message\ndata: {json.dumps(resp)}\n\n")
        return "".join(lines).encode("utf-8")

    def make_handler(self, responses: list[dict[str, Any]]):
        body = self.sse_body(responses)

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=body,
                )
            if request.method == "POST":
                try:
                    self.posted.append(json.loads(request.content.decode("utf-8")))
                except json.JSONDecodeError:
                    self.posted.append({})
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(405)

        return handler


class TestSseTransport:
    async def test_discovers_endpoint_and_pushes_messages(self) -> None:
        server = _SseServer("/rpc")
        transport = httpx.MockTransport(
            server.make_handler(
                [
                    {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}},
                ]
            )
        )
        client = httpx.AsyncClient(transport=transport)
        sse = SseTransport(
            url="http://mcp.test/events",
            client=client,
            connect_timeout=5.0,
        )
        try:
            await sse.start()
            assert sse.endpoint_url is not None
            assert sse.endpoint_url.endswith("/rpc")
            msg = await asyncio.wait_for(sse.recv(), timeout=2.0)
            assert msg["result"]["protocolVersion"] == "2024-11-05"
        finally:
            await sse.stop()
            await client.aclose()

    async def test_absolute_endpoint_passes_through(self) -> None:
        server = _SseServer(endpoint_path="https://other.host/rpc")
        # Handler must respond at the absolute endpoint host too.
        endpoint_body = server.sse_body([])

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=endpoint_body,
                )
            return httpx.Response(200, json={"ok": True})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sse = SseTransport(
            url="http://mcp.test/events", client=client, connect_timeout=2.0
        )
        try:
            await sse.start()
            assert sse.endpoint_url == "https://other.host/rpc"
        finally:
            await sse.stop()
            await client.aclose()

    async def test_send_posts_to_endpoint(self) -> None:
        server = _SseServer("/rpc")
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(server.make_handler([]))
        )
        sse = SseTransport(
            url="http://mcp.test/events", client=client, connect_timeout=2.0
        )
        try:
            await sse.start()
            await sse.send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            assert len(server.posted) == 1
            assert server.posted[0]["method"] == "tools/list"
        finally:
            await sse.stop()
            await client.aclose()

    async def test_rejects_non_2xx(self) -> None:
        async def deny(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, content=b"nope")

        client = httpx.AsyncClient(transport=httpx.MockTransport(deny))
        sse = SseTransport(
            url="http://mcp.test/events", client=client, connect_timeout=0.2
        )
        try:
            with pytest.raises(McpTransportError):
                await sse.start()
        finally:
            await client.aclose()


# --- McpClient via a fake transport ----------------------------------------


class _FakeTransport(McpTransport):
    """In-memory transport that pairs send() with scripted responses."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._responses: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def send(self, message: dict[str, Any]) -> None:
        if not self.started:
            raise McpTransportError("not started")
        self.sent.append(message)
        # Auto-respond to initialize and tools/list from a scripted buffer.
        if message.get("method") == "initialize":
            await self._responses.put(
                {"jsonrpc": "2.0", "id": message["id"], "result": {}}
            )

    async def recv(self) -> dict[str, Any]:
        return await self._responses.get()

    def enqueue(self, payload: dict[str, Any]) -> None:
        self._responses.put_nowait(payload)


class TestMcpClient:
    async def test_request_response_pairing(self, monkeypatch) -> None:
        fake = _FakeTransport()

        def fake_build(_cfg):  # noqa: ANN001
            return fake

        monkeypatch.setattr("deepseek_tui.mcp.client.build_transport", fake_build)
        client = McpClient(McpServerConfig(name="t", command="dummy"))
        await client.start()
        # Queue a tools/list result that matches the next request id (2)
        fake.enqueue(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tools": [{"name": "echo", "description": "demo"}]},
            }
        )
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "echo"
        await client.stop()

    async def test_request_timeout(self, monkeypatch) -> None:
        fake = _FakeTransport()

        def fake_build(_cfg):  # noqa: ANN001
            return fake

        monkeypatch.setattr("deepseek_tui.mcp.client.build_transport", fake_build)
        cfg = McpServerConfig(name="slow", command="dummy", read_timeout=0.05)
        client = McpClient(cfg)
        await client.start()
        # No response enqueued for tools/list → should time out
        with pytest.raises(McpError, match="timed out"):
            await client.list_tools()
        await client.stop()

    async def test_url_picks_sse_transport(self, monkeypatch) -> None:
        """HTTP URL previously hit 'not implemented yet'; now it builds SseTransport."""
        from deepseek_tui.mcp.client import build_transport

        cfg = McpServerConfig(name="http", url="http://mcp.test/events")
        transport = build_transport(cfg)
        assert isinstance(transport, SseTransport)


# --- AppRuntime integration ------------------------------------------------


@pytest_asyncio.fixture
async def runtime_with_mcp(tmp_path: Path) -> AsyncIterator[AppRuntime]:
    # Point the config at a written mcp.json that defines one disabled
    # stdio server so mcp_startup has something to report without
    # spawning anything real.
    mcp_config = tmp_path / "mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "servers": {
                    "demo": {
                        "command": "cat",
                        "enabled": False,
                    }
                }
            }
        )
    )
    cfg = Config()
    cfg.mcp_config_path = mcp_config
    rt = await AppRuntime.create(config=cfg, working_directory=tmp_path)
    try:
        yield rt
    finally:
        await rt.shutdown()


class TestAppRuntimeMcpStartup:
    async def test_lists_configured_servers(
        self, runtime_with_mcp: AppRuntime
    ) -> None:
        result = await runtime_with_mcp.mcp_startup()
        assert result["ok"] is True
        servers = result["summary"]["servers"]
        assert len(servers) == 1
        assert servers[0]["name"] == "demo"
        assert servers[0]["status"] == "disabled"
        assert servers[0]["transport"] == "stdio"

    async def test_mcp_disabled_feature(self, tmp_path: Path) -> None:
        cfg = Config()
        cfg.features.mcp = False
        rt = await AppRuntime.create(config=cfg, working_directory=tmp_path)
        try:
            result = await rt.mcp_startup()
            assert result["summary"]["note"] == "mcp-disabled"
        finally:
            await rt.shutdown()


class TestMcpManagerIntegration:
    async def test_manager_starts_stdio_round_trip(self, tmp_path: Path) -> None:
        """Full path: Manager → Client → StdioTransport via echo server."""
        # We write a tiny Python MCP server that responds to initialize +
        # tools/list — pure stdio, in-process child. Keeps the test hermetic.
        server_src = tmp_path / "mcp_echo.py"
        server_src.write_text(
            '''
import sys, json

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        rid = req.get("id")
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {}}
            print(json.dumps(resp), flush=True)
        elif method == "tools/list":
            tools = [{"name": "ping", "description": "p"}]
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}}
            print(json.dumps(resp), flush=True)
        elif method == "notifications/initialized":
            pass

if __name__ == "__main__":
    main()
'''
        )
        cfg = McpServerConfig(
            name="echo",
            command=sys.executable,
            args=[str(server_src)],
            read_timeout=5.0,
        )
        manager = McpManager([cfg])
        try:
            await manager.start_all()
            tools = await manager.discover_tools()
            # One tool, qualified with server prefix
            assert len(tools) == 1
            assert "ping" in tools[0]["function"]["name"]
        finally:
            await manager.stop_all()
