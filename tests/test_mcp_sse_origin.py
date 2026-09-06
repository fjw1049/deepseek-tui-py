import asyncio

import httpx
import pytest

from deepseek_tui.mcp.transport import McpTransportError, SseTransport


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://other.test/messages",
        "//other.test/messages",
        "http://service.test/messages",
        "https://service.test:444/messages",
        "https://service.test:0/messages",
        "https://user:password@service.test/messages",
        "file:///tmp/messages",
        "",
    ],
)
async def test_sse_rejects_endpoint_without_posting_credentials(endpoint):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=f"event: endpoint\ndata: {endpoint}\n\n",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), follow_redirects=True
    ) as client:
        transport = SseTransport(
            "https://service.test/sse",
            headers={"Authorization": "Bearer fake"},
            client=client,
            connect_timeout=10,
        )
        try:
            with pytest.raises(McpTransportError):
                await asyncio.wait_for(transport.start(), 1)
            with pytest.raises(McpTransportError):
                await transport.send({"id": 1})
            assert [r.method for r in requests] == ["GET"]
        finally:
            await transport.stop()


@pytest.mark.parametrize(
    "endpoint",
    ["/messages", "messages", "https://SERVICE.test:443/messages", "//service.test/messages"],
)
async def test_sse_same_origin_and_explicit_default_port_work(endpoint):
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(202)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=f"event: endpoint\ndata: {endpoint}\n\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        transport = SseTransport("https://service.test/sse", client=client)
        try:
            await transport.start()
            await transport.send({"id": 1})
            assert len(requests) == 2
            assert str(requests[1].url) == "https://service.test/messages"
        finally:
            await transport.stop()


async def test_sse_post_does_not_follow_redirect_with_custom_secret_headers():
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(307, headers={"location": "https://other.test/messages"})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="event: endpoint\ndata: /messages\n\n",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), follow_redirects=True
    ) as client:
        transport = SseTransport(
            "https://service.test/sse", headers={"X-Api-Key": "fake"}, client=client
        )
        try:
            await transport.start()
            with pytest.raises(McpTransportError):
                await transport.send({"id": 1})
            assert len(requests) == 2
        finally:
            await transport.stop()


@pytest.mark.parametrize("status", [302, 500])
async def test_sse_initial_failure_is_prompt_and_never_follows_redirect(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://other.test/sse"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), follow_redirects=True
    ) as client:
        transport = SseTransport("https://service.test/sse", client=client, connect_timeout=10)
        try:
            with pytest.raises(McpTransportError):
                await asyncio.wait_for(transport.start(), 1)
            assert len(requests) == 1
            assert transport._reader_task is None
        finally:
            await transport.stop()
