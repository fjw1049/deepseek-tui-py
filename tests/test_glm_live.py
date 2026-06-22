"""Live integration test: GLM-5.2 via Volces Ark (OpenAI-compatible endpoint).

Run: .venv/bin/python -m pytest tests/test_glm_live.py -s -q
"""

from __future__ import annotations

import json
import os

import pytest

from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.protocol.messages import Message, MessageRequest

ARK_KEY = os.environ.get("ARK_API_KEY", "")
pytestmark = [pytest.mark.live, pytest.mark.asyncio]


def _make_client():
    if not ARK_KEY:
        pytest.skip("ARK_API_KEY is not configured")
    cfg = Config()
    cfg.provider = "openai"
    cfg.api_key = ARK_KEY
    cfg.base_url = "https://ark.cn-beijing.volces.com/api/coding/v3"
    cfg.model = "GLM-5.2"
    cfg.default_text_model = "GLM-5.2"
    return build_llm_client(cfg)


def _make_anthropic_client():
    if not ARK_KEY:
        pytest.skip("ARK_API_KEY is not configured")
    cfg = Config(
        provider="volcengine-ark-anthropic",
        providers={
            "volcengine-ark-anthropic": ProviderConfig(api_key=ARK_KEY)
        },
    )
    return build_llm_client(cfg)


async def test_streaming_text_roundtrip():
    client = _make_client()
    try:
        req = MessageRequest(
            model="GLM-5.2",
            messages=[Message.user("Reply with exactly: HELLO_ZCODE")],
            max_tokens=2000,
            stream=True,
        )
        text, thinking, done = [], [], False
        async for ev in client.stream_chat_completion(req):
            et = type(ev).__name__
            if et == "StreamTextDelta":
                text.append(ev.text)
            elif et == "StreamThinkingDelta":
                thinking.append(ev.thinking)
            elif et == "StreamDone":
                done = True
        result = "".join(text)
        assert done, "StreamDone not received"
        assert "HELLO_ZCODE" in result, f"unexpected text: {result!r}"
        print(
            f"\n[PASS] streaming_text: {result!r} "
            f"(thinking chars: {len(''.join(thinking))})"
        )
    finally:
        await client.close()


async def test_tool_calling_roundtrip():
    client = _make_client()
    try:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            }
        ]
        req = MessageRequest(
            model="GLM-5.2",
            messages=[
                Message.user(
                    "What is the weather in Beijing? Use the get_weather tool."
                )
            ],
            tools=tools,
            max_tokens=2000,
            stream=True,
        )
        tool_calls = []
        async for ev in client.stream_chat_completion(req):
            et = type(ev).__name__
            if et == "StreamToolCallComplete":
                tool_calls.append(ev.tool_call)
        assert tool_calls, "no tool calls received"
        tc = tool_calls[0]
        assert tc.name == "get_weather", f"unexpected tool name: {tc.name}"
        assert tc.arguments.get("city"), f"missing city arg: {tc.arguments}"
        print(
            f"\n[PASS] tool_calling: name={tc.name} args={json.dumps(tc.arguments)}"
        )
    finally:
        await client.close()


async def test_anthropic_tool_calling_roundtrip():
    client = _make_anthropic_client()
    try:
        request = MessageRequest(
            model="GLM-5.2",
            messages=[Message.user("Use get_weather for Beijing.")],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get current weather for a city",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    },
                }
            ],
            tool_choice="required",
            max_tokens=2000,
        )
        calls = []
        async for event in client.stream_chat_completion(request):
            if type(event).__name__ == "StreamToolCallComplete":
                calls.append(event.tool_call)
        assert calls
        assert calls[0].name == "get_weather"
        assert calls[0].arguments.get("city")
    finally:
        await client.close()
