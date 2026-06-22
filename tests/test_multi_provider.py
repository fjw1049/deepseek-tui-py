"""Protocol contracts for OpenAI- and Anthropic-compatible providers."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.protocol.messages import (
    Message,
    MessageRequest,
    ToolUseBlock,
)
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    StreamToolCallComplete,
)
from deepseek_tui.tui.commands import cmd_provider
from deepseek_tui.server.threads import RuntimeThreadManager, StartTurnRequest


def _config(provider: str, *, protocol: str, base_url: str) -> Config:
    return Config(
        provider=provider,
        providers={
            provider: ProviderConfig(
                protocol=protocol,
                api_key="test-key",
                base_url=base_url,
                model="GLM-5.2",
            )
        },
    )


def test_factory_selects_anthropic_protocol() -> None:
    client = build_llm_client(
        _config(
            "ark-anthropic",
            protocol="anthropic",
            base_url="https://ark.example/api/coding",
        )
    )
    assert isinstance(client, AnthropicCompatClient)
    assert client._messages_url() == "https://ark.example/api/coding/v1/messages"


def test_ark_anthropic_registry_default_is_complete() -> None:
    config = Config(
        provider="volcengine-ark-anthropic",
        providers={
            "volcengine-ark-anthropic": ProviderConfig(api_key="test-key")
        },
    )

    provider = config.effective_provider_config()

    assert provider.protocol == "anthropic"
    assert provider.base_url == "https://ark.cn-beijing.volces.com/api/coding"
    assert provider.model == "GLM-5.2"


def test_factory_selects_openai_protocol_and_v3_url() -> None:
    client = build_llm_client(
        _config(
            "ark-openai",
            protocol="openai",
            base_url="https://ark.example/api/coding/v3",
        )
    )
    assert isinstance(client, DeepSeekClient)
    assert client._chat_completions_url() == (
        "https://ark.example/api/coding/v3/chat/completions"
    )


def test_runtime_resolves_custom_provider_without_top_level_overrides() -> None:
    config = Config(
        provider="deepseek",
        api_key="deepseek-key",
        base_url="https://api.deepseek.example",
        model="deepseek-v4-pro",
        providers={
            "qingyun": ProviderConfig(
                protocol="anthropic",
                api_key="custom-key",
                base_url="https://qingyun.example",
                model="claude-sonnet",
            )
        },
    )
    manager = object.__new__(RuntimeThreadManager)
    manager.config = config
    manager._llm_client = None
    manager._provider_clients = {}

    client = manager._get_llm_client("qingyun")
    cached = manager._get_llm_client("qingyun")
    routed_config = manager._config_for_provider("qingyun", "claude-opus")

    assert isinstance(client, AnthropicCompatClient)
    assert client.api_key == "custom-key"
    assert client.base_url == "https://qingyun.example"
    assert cached is client
    assert routed_config.provider == "qingyun"
    assert routed_config.model == "claude-opus"
    assert routed_config.api_key is None
    assert routed_config.base_url is None


def test_start_turn_request_keeps_provider_and_model_together() -> None:
    request = StartTurnRequest(
        prompt="hello",
        provider="qingyun",
        model="claude-sonnet",
    )
    assert request.provider == "qingyun"
    assert request.model == "claude-sonnet"


@pytest.mark.asyncio
async def test_openai_v3_stream_maps_tool_call_and_authorization() -> None:
    captured: dict[str, object] = {}
    chunk = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-1",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"a.py"}',
                            },
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
        )

    client = DeepSeekClient(
        api_key="test-key",
        base_url="https://ark.example/api/coding/v3",
        transport=httpx.MockTransport(handler),
    )
    try:
        events = [
            event
            async for event in client.stream_chat_completion(
                MessageRequest(
                    model="GLM-5.2",
                    messages=[Message.user("read a.py")],
                )
            )
        ]
    finally:
        await client.close()

    assert captured == {
        "url": "https://ark.example/api/coding/v3/chat/completions",
        "authorization": "Bearer test-key",
    }
    calls = [
        event.tool_call
        for event in events
        if isinstance(event, StreamToolCallComplete)
    ]
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "a.py"}


def test_anthropic_payload_maps_tools_and_tool_results() -> None:
    client = AnthropicCompatClient(
        api_key="test-key", base_url="https://ark.example/api/coding"
    )
    request = MessageRequest(
        model="GLM-5.2",
        system_prompt="system prompt",
        messages=[
            Message.user("inspect it"),
            Message.assistant_with_tools(
                [ToolUseBlock(id="call-1", name="read_file", input={"path": "a.py"})]
            ),
            Message.tool_result("call-1", "contents"),
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ],
        tool_choice="required",
    )

    payload = client._build_payload(request)

    assert payload["system"] == "system prompt"
    assert payload["tools"][0]["input_schema"]["properties"]["path"]
    assert payload["tool_choice"] == {"type": "any"}
    assert payload["messages"][1]["content"][0] == {
        "type": "tool_use",
        "id": "call-1",
        "name": "read_file",
        "input": {"path": "a.py"},
    }
    assert payload["messages"][2]["role"] == "user"
    assert payload["messages"][2]["content"][0]["tool_use_id"] == "call-1"


@pytest.mark.asyncio
async def test_anthropic_stream_maps_text_tool_call_usage_and_headers() -> None:
    captured: dict[str, object] = {}

    def sse_event(name: str, payload: dict[str, object]) -> str:
        return f"event: {name}\ndata: {json.dumps(payload)}\n"

    sse = "\n".join(
        [
            sse_event(
                "message_start",
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 7}},
                },
            ),
            sse_event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": "hello "},
                },
            ),
            sse_event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "world"},
                },
            ),
            sse_event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "read_file",
                        "input": {},
                    },
                },
            ),
            sse_event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"path":"a.py"}',
                    },
                },
            ),
            sse_event(
                "content_block_stop",
                {"type": "content_block_stop", "index": 1},
            ),
            sse_event(
                "message_delta",
                {"type": "message_delta", "usage": {"output_tokens": 5}},
            ),
            sse_event("message_stop", {"type": "message_stop"}),
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse,
        )

    client = AnthropicCompatClient(
        api_key="test-key",
        base_url="https://ark.example/api/coding",
        transport=httpx.MockTransport(handler),
    )
    try:
        events = [
            event
            async for event in client.stream_chat_completion(
                MessageRequest(model="GLM-5.2", messages=[Message.user("go")])
            )
        ]
    finally:
        await client.close()

    assert captured["url"] == "https://ark.example/api/coding/v1/messages"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "hello world" == "".join(
        event.text for event in events if isinstance(event, StreamTextDelta)
    )
    calls = [event.tool_call for event in events if isinstance(event, StreamToolCallComplete)]
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "a.py"}
    done = [event for event in events if isinstance(event, StreamDone)]
    assert len(done) == 1
    assert done[0].usage is not None
    assert done[0].usage.input_tokens == 7
    assert done[0].usage.output_tokens == 5


def test_provider_switch_builds_client_with_new_model() -> None:
    config = Config(
        provider="deepseek",
        model="deepseek-v4-pro",
        providers={
            "ark": ProviderConfig(
                api_key="test-key",
                base_url="https://ark.example/v3",
                model="GLM-5.2",
            )
        },
    )
    seen: list[str | None] = []
    new_client = SimpleNamespace(api_key="test-key")
    old_client = SimpleNamespace()
    app = SimpleNamespace(
        config=config,
        _engine=SimpleNamespace(
            client=old_client,
            turn_loop=SimpleNamespace(client=old_client),
            default_model="deepseek-v4-pro",
        ),
    )
    app._build_client = lambda: seen.append(config.model) or new_client
    app.query_one = lambda widget: (_ for _ in ()).throw(RuntimeError())

    result = cmd_provider("ark", app)

    assert result.error == ""
    assert seen == ["GLM-5.2"]
    assert app._engine.client is new_client
    assert app._engine.turn_loop.client is new_client
