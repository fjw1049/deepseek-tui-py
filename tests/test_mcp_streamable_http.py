"""Streamable HTTP transport + Cursor-style mcp.json fields."""

from __future__ import annotations

import httpx
import pytest

from deepseek_tui.mcp.client import build_transport
from deepseek_tui.mcp.config import McpServerConfig, servers_from_document
from deepseek_tui.mcp.transport import StreamableHttpTransport, _iter_sse_json_objects


def test_servers_from_document_parses_headers_and_streamablehttp_type() -> None:
    configs = servers_from_document(
        {
            "filo-mail-mcp": {
                "type": "streamablehttp",
                "url": "http://127.0.0.1:3129/mcp",
                "headers": {"Authorization": "Bearer secret"},
            }
        }
    )
    assert len(configs) == 1
    cfg = configs[0]
    assert cfg.name == "filo-mail-mcp"
    assert cfg.url == "http://127.0.0.1:3129/mcp"
    assert cfg.headers["Authorization"] == "Bearer secret"
    assert cfg.transport == "streamablehttp"


def test_build_transport_selects_streamable_http() -> None:
    transport = build_transport(
        McpServerConfig(
            name="filo",
            url="http://127.0.0.1:3129/mcp",
            headers={"Authorization": "Bearer x"},
            transport="streamablehttp",
        )
    )
    assert isinstance(transport, StreamableHttpTransport)
    assert transport.headers["Authorization"] == "Bearer x"


def test_build_transport_url_without_hint_stays_sse() -> None:
    from deepseek_tui.mcp.transport import SseTransport

    transport = build_transport(
        McpServerConfig(name="legacy", url="http://127.0.0.1:9/sse", headers={"A": "1"})
    )
    assert isinstance(transport, SseTransport)
    assert transport.headers["A"] == "1"


def test_iter_sse_json_objects() -> None:
    body = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{}}\n'
        "\n"
        'data: {"jsonrpc":"2.0","method":"ping"}\n'
        "\n"
    )
    items = _iter_sse_json_objects(body)
    assert items[0]["id"] == 1
    assert items[1]["method"] == "ping"


@pytest.mark.asyncio
async def test_streamable_http_send_json_response_queues_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer secret"
        assert "application/json" in (request.headers.get("Accept") or "")
        return httpx.Response(
            200,
            headers={"Mcp-Session-Id": "sess-1", "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
        )

    transport = StreamableHttpTransport(
        "http://mcp.test/mcp",
        headers={"Authorization": "Bearer secret"},
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await transport.start()
    await transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    message = await transport.recv()
    assert message["result"]["ok"] is True
    assert transport._session_id == "sess-1"
    await transport.stop()


@pytest.mark.asyncio
async def test_streamable_http_echoes_session_id_on_next_request() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("mcp-session-id"))
        if len(seen) == 1:
            return httpx.Response(
                200,
                headers={"mcp-session-id": "abc", "Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": 1, "result": {}},
            )
        return httpx.Response(202)

    transport = StreamableHttpTransport(
        "http://mcp.test/mcp",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await transport.start()
    await transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    await transport.recv()
    await transport.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    await transport.stop()
    assert seen[0] is None
    assert seen[1] == "abc"
