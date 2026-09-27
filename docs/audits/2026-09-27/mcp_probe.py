"""Audit 10 offline characterization. Uses synthetic transports/configs only."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from deepseek_tui.mcp import store
from deepseek_tui.mcp.client import McpClient, McpToolDescriptor, qualify_tool_name
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.mcp.transport import StdioTransport, StreamableHttpTransport


class FakeClient:
    instances = []
    gate = None

    def __init__(self, config):
        self.config = config
        self.running = False
        self.instances.append(self)

    @property
    def is_running(self):
        return self.running

    async def start(self):
        if self.gate is not None:
            if len(self.instances) == 2:
                self.gate.set()
            await self.gate.wait()
        self.running = True

    async def stop(self):
        self.running = False

    async def list_tools(self):
        return [
            McpToolDescriptor(name="do-thing", description="first"),
            McpToolDescriptor(name="do_thing", description="second"),
        ]

    async def list_resources(self):
        return [{"uri": "fixture://resource"}]

    async def call_tool(self, name, args):
        return {"content": [{"type": "text", "text": name}]}


async def main(root):
    out = {}
    FakeClient.instances = []
    FakeClient.gate = asyncio.Event()
    manager = McpManager([McpServerConfig(name="fixture", command="not-executed")])
    with patch("deepseek_tui.mcp.manager.McpClient", FakeClient):
        clients = await asyncio.gather(
            manager._ensure_client("fixture"), manager._ensure_client("fixture")
        )
        await manager.stop_all()
    out["concurrent_connection_creation"] = {
        "distinct_clients": len({id(c) for c in clients}),
        "running_after_stop_all": sum(c.running for c in clients),
    }
    for c in clients:
        await c.stop()
    FakeClient.gate = None

    path = root / "mcp.json"
    store.add_server_config(path, "fixture", command="not-executed")
    manager = McpManager(
        [McpServerConfig(name="fixture", command="not-executed")], config_path=path
    )
    with patch("deepseek_tui.mcp.manager.McpClient", FakeClient):
        tools = await manager.discover_tools()
        out["colliding_tool_names"] = {
            "raw_count": 2,
            "catalog_count": len(tools),
            "route": manager._resolve_qualified(qualify_tool_name("fixture", "do-thing")),
        }
        before = path.stat().st_mtime
        store.set_server_enabled(path, "fixture", False)
        os.utime(path, (before + 2, before + 2))
        assert await manager.reload_if_config_changed()
        result = await manager.call_tool(qualify_tool_name("fixture", "do-thing"), {})
        resources = await manager.list_resources()
        out["disabled_server_after_reload"] = {
            "enabled": manager.server_config("fixture").enabled,
            "call_result": result["content"][0]["text"],
            "resource_count": len(resources["fixture"]),
        }
        await manager.stop_all()

    # Closing the manager does not cancel a shielded discovery still in progress.
    gate = asyncio.Event()
    entered = asyncio.Event()
    manager = McpManager([])

    async def discovering():
        entered.set()
        await gate.wait()
        manager._discovered_tools_cache = [{"fixture": "late publication"}]
        return manager._discovered_tools_cache

    with patch.object(manager, "_discover_tools_fresh", side_effect=discovering):
        task = asyncio.create_task(manager.discover_tools())
        await entered.wait()
        await manager.stop_all()
        gate.set()
        await task
    out["cache_published_after_stop_all"] = manager.cached_tools() is not None

    cfg = McpServerConfig(name="fixture", command="not-executed", read_timeout=0.001)
    client = McpClient(cfg)
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowSend:
        async def send(self, message):
            entered.set()
            await release.wait()
            client._pending.pop(message["id"]).set_result({"result": {"ok": True}})

    client._transport = SlowSend()
    task = asyncio.create_task(client._send_request("fixture", {}, timeout=0.001))
    await entered.wait()
    await asyncio.sleep(0.02)
    out["request_survives_20x_timeout_while_sending"] = not task.done()
    release.set()
    await task
    client._transport = SimpleNamespace(send=AsyncMock())
    task = asyncio.create_task(client._send_request("fixture", {}, timeout=60))
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    out["pending_after_request_cancel"] = len(client._pending)
    client._pending.clear()

    first = asyncio.Event()
    finish = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            first.set()
            yield b'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
            await finish.wait()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=Body()
            )
        )
    ) as http:
        transport = StreamableHttpTransport("https://example.invalid", client=http)
        await transport.start()
        task = asyncio.create_task(transport.send({"id": 1, "method": "fixture"}))
        await first.wait()
        await asyncio.sleep(0)
        out["http_sse_response_delivered_before_body_eof"] = not transport._queue.empty()
        finish.set()
        await task
        assert (await transport.recv())["result"]["ok"]
        await transport.stop()

    client = McpClient(cfg)
    client._send_request = AsyncMock(
        return_value={"tools": [{"name": "first"}], "nextCursor": "page-2"}
    )
    tools = await client.list_tools()
    out["pagination"] = {
        "names": [t.name for t in tools],
        "rpc_calls": client._send_request.await_count,
    }

    reader = asyncio.StreamReader()
    reader.feed_data((json.dumps({"result": {"text": "x" * 70000}}) + "\n").encode())
    transport = StdioTransport("not-executed")
    transport._process = SimpleNamespace(stdout=reader)
    try:
        await transport.recv()
    except Exception as exc:
        out["stdio_70kb_frame_exception"] = type(exc).__name__

    path = root / "concurrent.json"
    original = store.load_raw_document
    barrier = threading.Barrier(2)

    def snapshot(path):
        result = original(path)
        barrier.wait(timeout=3)
        return result

    with (
        patch.object(store, "load_raw_document", side_effect=snapshot),
        ThreadPoolExecutor(2) as pool,
    ):
        list(
            pool.map(
                lambda name: store.add_server_config(path, name, command="not-executed"),
                ["first", "second"],
            )
        )
    out["servers_after_two_concurrent_adds"] = len(store.load_raw_document(path)["mcp"]["servers"])
    return out


if __name__ == "__main__":
    with TemporaryDirectory(prefix="mcp-audit10-") as root:
        print(json.dumps(asyncio.run(main(Path(root))), indent=2))
