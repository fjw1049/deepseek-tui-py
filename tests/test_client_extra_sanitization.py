"""Last-mile hardening for config-supplied ``extra_body`` / ``extra_headers``.

Provider config (user-level or phished) may try to override the
conversation body or credential headers; both clients must strip the
blocked keys at the point of use while keeping benign extras.
"""

from __future__ import annotations

import httpx
import pytest

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.protocol.messages import Message, MessageRequest


def _request(**kwargs: object) -> MessageRequest:
    return MessageRequest(model="real-model", messages=[Message.user("hi")], **kwargs)  # type: ignore[arg-type]


# --- extra_body ---------------------------------------------------------------


def test_deepseek_extra_body_cannot_override_conversation_core() -> None:
    client = DeepSeekClient(api_key="k")
    request = _request(
        extra_body={
            "messages": [{"role": "user", "content": "evil"}],
            "model": "evil-model",
            "tools": [{"type": "function", "function": {"name": "evil"}}],
            "tool_choice": "none",
            "stream": False,
            "temperature": 0.1,
        }
    )

    payload = client._build_payload(request)

    assert payload["model"] == "real-model"
    assert payload["stream"] is True
    assert payload["messages"][-1] == {"role": "user", "content": "hi"}
    assert "tools" not in payload
    assert "tool_choice" not in payload
    # Benign vendor keys still pass through.
    assert payload["temperature"] == 0.1


def test_anthropic_extra_body_cannot_override_conversation_core() -> None:
    client = AnthropicCompatClient(api_key="k", base_url="https://api.example")
    request = _request(
        max_tokens=64,
        system_prompt="real-system",
        extra_body={
            "messages": [{"role": "user", "content": "evil"}],
            "model": "evil-model",
            "system": "pwned-system",
            "tools": [],
            "tool_choice": {"type": "none"},
            "stream": False,
            "top_k": 5,
        }
    )

    payload = client._build_payload(request)

    assert payload["model"] == "real-model"
    assert payload["stream"] is True
    assert payload["system"] == "real-system"
    assert payload["messages"][-1]["content"] == [{"type": "text", "text": "hi"}]
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert payload["top_k"] == 5


# --- extra_headers ------------------------------------------------------------

_EVIL_HEADERS = {
    "Authorization": "Bearer stolen",
    "X-Api-Key": "stolen",
    "COOKIE": "session=stolen",
    "X-Custom": "kept",
}


async def _capture_request(client: object) -> httpx.Request:
    captured: dict[str, httpx.Request] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="data: [DONE]\n\n",
        )

    client.transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    try:
        async for _ in client.stream_chat_completion(_request()):  # type: ignore[attr-defined]
            pass
    finally:
        await client.close()  # type: ignore[attr-defined]
    return captured["request"]


@pytest.mark.asyncio
async def test_deepseek_extra_headers_cannot_override_credentials() -> None:
    client = DeepSeekClient(api_key="real-key", extra_headers=dict(_EVIL_HEADERS))

    request = await _capture_request(client)

    assert request.headers["authorization"] == "Bearer real-key"
    assert "x-api-key" not in request.headers
    assert "cookie" not in request.headers
    assert request.headers["x-custom"] == "kept"


@pytest.mark.asyncio
async def test_anthropic_extra_headers_cannot_override_credentials() -> None:
    client = AnthropicCompatClient(
        api_key="real-key",
        base_url="https://api.example",
        extra_headers=dict(_EVIL_HEADERS),
    )

    request = await _capture_request(client)

    assert request.headers["x-api-key"] == "real-key"
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers
    assert request.headers["x-custom"] == "kept"


# --- shared helper ------------------------------------------------------------


def test_sanitize_helpers_drop_only_blocked_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from deepseek_tui.client.sanitize import (
        sanitize_extra_body,
        sanitize_extra_headers,
    )

    with caplog.at_level("WARNING"):
        body = sanitize_extra_body(
            {"messages": [], "model": "x", "system": "pwned", "temperature": 0.2}
        )
        headers = sanitize_extra_headers({"AUTHORIZATION": "s", "X-Foo": "1"})

    assert body == {"temperature": 0.2}
    assert headers == {"X-Foo": "1"}
    warnings = [r.getMessage() for r in caplog.records]
    assert any("messages" in w for w in warnings)
    assert any("model" in w for w in warnings)
    assert any("AUTHORIZATION" in w for w in warnings)
