"""Regression coverage for audit 10; local fixtures and mock HTTP only."""

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deepseek_tui.mcp import store
from deepseek_tui.mcp.client import McpClient, McpError, McpToolDescriptor, qualify_tool_name
from deepseek_tui.mcp.config import McpServerConfig, ToolFilter
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.mcp.transport import McpTransportError, StdioTransport, StreamableHttpTransport


@pytest.fixture
def fake_client(monkeypatch):
    class Fake:
        instances = []
        gate = None
        entered = None
        descriptors = [McpToolDescriptor(name="run", description="fixture")]

        def __init__(self, config):
            self.config = config
            self.running = False
            self.stopped = False
            self.instances.append(self)

        @property
        def is_running(self):
            return self.running

        async def start(self):
            if self.entered:
                self.entered.set()
            if self.gate:
                await self.gate.wait()
            self.running = True

        async def stop(self):
            self.running = False
            self.stopped = True

        async def list_tools(self):
            return self.descriptors

        async def call_tool(self, name, args):
            return {"name": name}

        async def list_resources(self):
            return [{"uri": "fixture://one"}]

        async def read_resource(self, uri):
            return {"uri": uri}

    monkeypatch.setattr("deepseek_tui.mcp.manager.McpClient", Fake)
    return Fake


def manager():
    return McpManager([McpServerConfig(name="fixture", command="not-executed")])


async def test_connection_is_shared_and_one_cancelled_waiter_does_not_abort_it(fake_client):
    fake_client.gate = asyncio.Event()
    fake_client.entered = asyncio.Event()
    mgr = manager()
    a = asyncio.create_task(mgr._ensure_client("fixture"))
    b = asyncio.create_task(mgr._ensure_client("fixture"))
    await fake_client.entered.wait()
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    fake_client.gate.set()
    client = await b
    assert len(fake_client.instances) == 1
    assert client.is_running
    assert await mgr._ensure_client("fixture") is client
    await mgr.stop_all()
    assert client.stopped
    assert not mgr._clients


async def test_stop_cancels_connection_before_it_can_publish(fake_client):
    fake_client.gate = asyncio.Event()
    fake_client.entered = asyncio.Event()
    mgr = manager()
    task = asyncio.create_task(mgr._ensure_client("fixture"))
    await fake_client.entered.wait()
    await mgr.stop_all()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake_client.instances[0].stopped
    assert not mgr._clients
    assert not mgr._owned_tasks


async def test_stdio_stop_bounds_wait_after_kill(monkeypatch):
    class StuckProcess:
        killed = False

        def terminate(self):
            pass

        def kill(self):
            self.killed = True

        async def wait(self):
            await asyncio.Event().wait()

    transport = StdioTransport("not-executed", [])
    process = StuckProcess()
    transport._process = process
    real_wait_for = asyncio.wait_for

    async def short_wait(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr("deepseek_tui.mcp.transport.asyncio.wait_for", short_wait)
    with pytest.raises(asyncio.TimeoutError):
        await transport.stop()
    assert process.killed


async def test_reload_reports_invalidated_connection_as_error(tmp_path, fake_client):
    path = tmp_path / "mcp.json"
    store.add_server_config(path, "fixture", command="not-executed")
    fake_client.gate = asyncio.Event()
    fake_client.entered = asyncio.Event()
    mgr = McpManager([McpServerConfig(name="fixture", command="not-executed")], config_path=path)
    pending = asyncio.create_task(mgr._ensure_client("fixture"))
    await fake_client.entered.wait()
    store.set_server_enabled(path, "fixture", False)
    await mgr.reload_if_config_changed()
    with pytest.raises(McpError, match="invalidated by config reload"):
        await pending
    await mgr.stop_all()


async def test_stop_cancels_shared_discovery(fake_client):
    mgr = manager()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def discover():
        entered.set()
        await release.wait()
        mgr._discovered_tools_cache = [{"late": True}]
        return mgr._discovered_tools_cache

    with patch.object(mgr, "_discover_tools_fresh", side_effect=discover):
        task = asyncio.create_task(mgr.discover_tools())
        await entered.wait()
        await mgr.stop_all()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert mgr.cached_tools() is None


async def test_cancel_discovery_waiter_preserves_single_shared_task(fake_client):
    mgr = manager()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def tools(self):
        entered.set()
        await release.wait()
        return self.descriptors

    with patch.object(fake_client, "list_tools", tools):
        a = asyncio.create_task(mgr.discover_tools())
        await entered.wait()
        a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await a
        original = mgr._discover_inflight
        b = asyncio.create_task(mgr.discover_tools())
        await asyncio.sleep(0)
        assert mgr._discover_inflight is original
        release.set()
        assert len(await b) == 1
    await mgr.stop_all()


@pytest.mark.parametrize("change", ["disable", "remove", "filter", "delete_file"])
async def test_reload_invalidates_old_routes_and_resources(tmp_path, fake_client, change):
    path = tmp_path / "mcp.json"
    store.add_server_config(path, "fixture", command="not-executed")
    mgr = McpManager([McpServerConfig(name="fixture", command="not-executed")], config_path=path)
    await mgr.discover_tools()
    before = path.stat().st_mtime
    if change == "disable":
        store.set_server_enabled(path, "fixture", False)
    elif change == "remove":
        store.remove_server_config(path, "fixture")
    elif change == "delete_file":
        path.unlink()
    else:
        doc = store.load_raw_document(path)
        doc["mcp"]["servers"]["fixture"]["disabled_tools"] = ["run"]
        store.save_document(path, doc)
    if path.exists():
        os.utime(path, (before + 2, before + 2))
    with pytest.raises(McpError):
        await mgr.call_tool(qualify_tool_name("fixture", "run"), {})
    assert mgr.cached_tools() is None
    if change != "filter":
        assert await mgr.list_resources() == {}
        with pytest.raises(McpError):
            await mgr.read_resource("fixture", "fixture://one")
    await mgr.stop_all()


async def test_tool_filter_checked_even_for_cached_map(fake_client):
    mgr = manager()
    await mgr.discover_tools()
    mgr.server_config("fixture").tool_filter = ToolFilter(deny=["run"])
    with pytest.raises(McpError, match="disabled"):
        await mgr.call_tool("mcp_fixture_run", {})
    await mgr.stop_all()


async def test_old_discovery_cannot_publish_after_reload(tmp_path, fake_client):
    path = tmp_path / "mcp.json"
    store.add_server_config(path, "fixture", command="not-executed")
    mgr = McpManager([McpServerConfig(name="fixture", command="not-executed")], config_path=path)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def tools(self):
        entered.set()
        await release.wait()
        return self.descriptors

    with patch.object(fake_client, "list_tools", tools):
        old = asyncio.create_task(mgr.discover_tools())
        await entered.wait()
        before = path.stat().st_mtime
        store.set_server_enabled(path, "fixture", False)
        os.utime(path, (before + 2, before + 2))
        assert await mgr.reload_if_config_changed()
        release.set()
        with pytest.raises(McpError, match="invalidated"):
            await old
    assert mgr.cached_tools() is None
    await mgr.stop_all()


@pytest.mark.parametrize("stage", ["send", "wait"])
async def test_cancel_always_releases_pending(stage):
    client = McpClient(McpServerConfig(name="fixture", command="not-executed"))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send(message):
        entered.set()
        if stage == "send":
            await release.wait()

    client._transport = SimpleNamespace(send=send)
    task = asyncio.create_task(client._send_request("fixture", {}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client._pending == {}


async def test_timeout_covers_send_and_normalizes_http_failure():
    client = McpClient(McpServerConfig(name="fixture", command="not-executed"))

    async def stalled(message):
        await asyncio.Event().wait()

    client._transport = SimpleNamespace(send=stalled)
    with pytest.raises(McpError, match="timed out"):
        await client._send_request("fixture", {}, timeout=0.01)
    assert not client._pending
    client._transport = SimpleNamespace(send=AsyncMock(side_effect=httpx.ReadError("fixture")))
    with pytest.raises(McpError):
        await client._send_request("fixture", {})
    assert not client._pending


@pytest.mark.parametrize("field", ["tools", "resources"])
async def test_paginated_list_reads_all_pages(field):
    client = McpClient(McpServerConfig(name="fixture", command="not-executed"))
    client._send_request = AsyncMock(
        side_effect=[
            {field: [], "nextCursor": "two"},
            {field: [{"name": "last", "uri": "fixture://last"}]},
        ]
    )
    result = await (client.list_tools() if field == "tools" else client.list_resources())
    assert len(result) == 1
    assert client._send_request.await_args_list[1].args[1] == {"cursor": "two"}


@pytest.mark.parametrize(
    "second", [{"tools": [], "nextCursor": "two"}, {"tools": {}}, {"tools": [], "nextCursor": 42}]
)
async def test_pagination_rejects_bad_or_repeated_cursor(second):
    client = McpClient(McpServerConfig(name="fixture", command="not-executed"))
    client._send_request = AsyncMock(
        side_effect=[{"tools": [{"name": "first"}], "nextCursor": "two"}, second]
    )
    with pytest.raises(McpError):
        await client.list_tools()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
async def test_stream_result_returns_before_http_eof_and_closes_response(newline):
    class Body(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            wire = (
                b"event: message"
                + newline
                + b'data: {"jsonrpc":"2.0",'
                + newline
                + b'data: "id":1,"result":{"ok":true}}'
                + newline
                + newline
            )
            # Split CRLF as well as JSON across chunks.
            for byte in wire:
                yield bytes([byte])
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    body = Body()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=body
            )
        )
    ) as http:
        transport = StreamableHttpTransport("https://example.invalid", client=http)
        await transport.start()
        await asyncio.wait_for(transport.send({"id": 1, "method": "fixture"}), timeout=1)
        assert (await transport.recv())["result"]["ok"]
        assert body.closed
        await transport.stop()


async def test_stream_frame_limit_is_enforced(monkeypatch):
    monkeypatch.setattr("deepseek_tui.mcp.transport.MAX_MCP_MESSAGE_BYTES", 128)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, text="data: " + ("x" * 200)
            )
        )
    ) as http:
        transport = StreamableHttpTransport("https://example.invalid", client=http)
        await transport.start()
        with pytest.raises(McpTransportError, match="size limit"):
            await transport.send({"id": 1})
        await transport.stop()


async def test_large_stdio_json_and_unterminated_stderr_are_drained():
    code = 'import sys,json;sys.stderr.write("x"*100000+"tail\\n");sys.stderr.flush();print(json.dumps({"result":{"text":"y"*70000}}))'
    transport = StdioTransport(sys.executable, ["-c", code])
    await transport.start()
    try:
        result = await asyncio.wait_for(transport.recv(), timeout=3)
        assert len(result["result"]["text"]) == 70000
        await asyncio.wait_for(transport._stderr_task, timeout=1)
        assert any("tail" in line for line in transport._stderr_tail)
        assert all(len(line) <= 301 for line in transport._stderr_tail)
    finally:
        await transport.stop()


@pytest.mark.parametrize("policy", ["progressive", "on_focus"])
async def test_collisions_are_removed_from_catalog_and_routing(fake_client, policy):
    fake_client.descriptors = [
        McpToolDescriptor(name="do-thing", description="first"),
        McpToolDescriptor(name="do_thing", description="second"),
    ]
    mgr = McpManager([McpServerConfig(name="fixture", command="not-executed", load_policy=policy)])
    tools = await (
        mgr.discover_tools()
        if policy == "progressive"
        else mgr.ensure_focus_server_discovered("fixture")
    )
    assert tools == []
    assert mgr._resolve_qualified("mcp_fixture_do_thing") is None
    with pytest.raises(McpError):
        await mgr.call_tool("mcp_fixture_do_thing", {})
    await mgr.stop_all()


def test_parallel_config_mutations_preserve_all_entries(tmp_path):
    path = tmp_path / "mcp.json"
    with ThreadPoolExecutor(4) as pool:
        list(
            pool.map(
                lambda i: store.add_server_config(path, str(i), command="not-executed"), range(16)
            )
        )
    assert len(store.load_raw_document(path)["mcp"]["servers"]) == 16


async def test_cancelled_stop_still_drains_clients(fake_client):
    mgr = manager()
    client = await mgr._ensure_client("fixture")
    entered, release = asyncio.Event(), asyncio.Event()

    async def stop():
        entered.set()
        await release.wait()
        client.stopped = True

    client.stop = stop
    closing = asyncio.create_task(mgr.stop_all())
    await entered.wait()
    closing.cancel()
    await asyncio.sleep(0)
    assert mgr._closing
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert client.stopped
    assert not mgr._clients
    assert not mgr._closing


async def test_distinct_servers_connect_in_parallel(fake_client):
    fake_client.gate = asyncio.Event()
    mgr = McpManager([McpServerConfig(name=n, command="unused") for n in ("one", "two")])
    tasks = [asyncio.create_task(mgr._ensure_client(n)) for n in mgr.server_names]
    for _ in range(10):
        if len(fake_client.instances) == 2:
            break
        await asyncio.sleep(0)
    assert len(fake_client.instances) == 2
    fake_client.gate.set()
    await asyncio.gather(*tasks)
    await mgr.stop_all()


async def test_cancelled_reload_still_retires_old_client(tmp_path, fake_client):
    path = tmp_path / "mcp.json"
    store.add_server_config(path, "fixture", command="unused")
    mgr = McpManager([McpServerConfig(name="fixture", command="unused")], config_path=path)
    client = await mgr._ensure_client("fixture")
    before = path.stat().st_mtime
    store.set_server_enabled(path, "fixture", False)
    os.utime(path, (before + 2, before + 2))
    entered, release = asyncio.Event(), asyncio.Event()

    async def stop():
        entered.set()
        await release.wait()
        client.stopped = True

    client.stop = stop
    reloading = asyncio.create_task(mgr.reload_if_config_changed())
    await entered.wait()
    reloading.cancel()
    await asyncio.sleep(0)
    assert not mgr.server_config("fixture").enabled
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await reloading
    assert client.stopped
    assert not mgr._clients
    await mgr.stop_all()
