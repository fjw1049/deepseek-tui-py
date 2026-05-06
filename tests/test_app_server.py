"""Tests for app server."""

import pytest

from deepseek_tui.app_server import AppServerOptions
from deepseek_tui.app_server.routes import healthz
from deepseek_tui.app_server.sse import SseStream


def test_app_server_options_defaults() -> None:
    """Test app server options defaults."""
    options = AppServerOptions()
    assert options.listen == "127.0.0.1:8080"
    assert options.config_path is None


@pytest.mark.asyncio
async def test_healthz_endpoint() -> None:
    """Test healthz endpoint."""
    result = await healthz()
    assert result["status"] == "ok"
    assert result["protocol"] == "v2"
    assert result["service"] == "deepseek-app-server"


@pytest.mark.asyncio
async def test_sse_stream() -> None:
    """Test SSE stream."""
    stream = SseStream()

    # Send events
    await stream.send({"type": "test", "data": "hello"})
    await stream.send({"type": "test", "data": "world"})
    await stream.close()

    # Collect events
    events = []
    async for event in stream:
        events.append(event)

    assert len(events) == 2
    assert "hello" in events[0]
    assert "world" in events[1]
