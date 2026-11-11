"""Real socket regression for the fetch timeout/escalation path."""

import asyncio

import pytest

from deepseek_tui.tools import web
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.utils.network_escalation import host_timeout_count


@pytest.mark.asyncio
async def test_direct_fetch_preserves_timeout_for_retry_guidance(tmp_path, monkeypatch):
    connections = set()
    requests = []
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")

    async def stall(reader, writer):
        task = asyncio.current_task()
        connections.add(task)
        try:
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            # The peer must time out waiting for a real HTTP response.
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            connections.discard(task)

    # Only the test's loopback address bypasses the public-fetch guard.
    reject_private = web._reject_private_fetch_url
    async with await asyncio.start_server(stall, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}/slow.txt"
        monkeypatch.setattr(web, "_reject_private_fetch_url", lambda value: None if value == url else reject_private(value))
        context = ToolContext(working_directory=tmp_path, timeout_ms=100)
        tool = web.FetchUrlTool()
        try:
            for attempt in range(1, 3):
                with pytest.raises(ToolError, match="fetch_url timed out") as error:
                    await tool.execute({"url": url}, context)
                assert host_timeout_count(context, url) == attempt
                assert ("mirror/CDN" in str(error.value)) == (attempt == 2)
            assert len(requests) == 2
        finally:
            if connections:
                await asyncio.gather(*connections)
