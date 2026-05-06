from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.client.pricing import ModelPricing, PricingTable
from deepseek_tui.client.retry import RetryConfig
from deepseek_tui.client.streaming import OpenAIStreamParser, parse_json_object
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    StreamToolCallComplete,
    Usage,
)
from deepseek_tui.tools.file_tools import ReadFileTool
from deepseek_tui.tools.registry import ToolRegistry


class FakeRetryClient(LLMClient):
    def __init__(self, fail_before_success: int, emit_text: bool = False) -> None:
        super().__init__(
            RetryConfig(max_transparent_retries=2, max_error_retries=2, base_delay=0.0)
        )
        self.fail_before_success = fail_before_success
        self.emit_text = emit_text
        self.calls = 0

    async def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[object]:
        self.calls += 1
        if self.calls <= self.fail_before_success:
            if self.emit_text:
                yield StreamTextDelta(text="partial")
            raise httpx.ReadTimeout("timeout")
        yield StreamDone()


class FakeSSE:
    def __init__(self, data: str) -> None:
        self.data = data


class FakeEventSource:
    def __init__(self, events: list[FakeSSE]) -> None:
        self._events = events

    async def __aenter__(self) -> FakeEventSource:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def aiter_sse(self) -> AsyncIterator[FakeSSE]:
        for event in self._events:
            yield event


def test_parse_json_object_handles_invalid_json() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object("[1, 2]") == {"value": [1, 2]}
    assert parse_json_object("{") == {"raw": "{"}


def test_stream_parser_emits_text_tool_and_done() -> None:
    parser = OpenAIStreamParser()
    tool_chunk = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-1",
                            "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'},
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    stop_chunk = {
        "choices": [{"delta": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    tool_events = parser.parse_chunk(tool_chunk)
    stop_events = parser.parse_chunk(stop_chunk)

    assert any(isinstance(event, StreamToolCallComplete) for event in tool_events)
    assert any(isinstance(event, StreamTextDelta) for event in stop_events)
    assert any(isinstance(event, StreamDone) for event in stop_events)


@pytest.mark.asyncio
async def test_retry_client_retries_before_content() -> None:
    client = FakeRetryClient(fail_before_success=2)
    request = MessageRequest(model="deepseek-chat")

    events = [event async for event in client.stream_with_retry(request)]

    assert client.calls == 3
    assert len(events) == 1
    assert isinstance(events[0], StreamDone)


@pytest.mark.asyncio
async def test_retry_client_emits_error_after_partial_content() -> None:
    client = FakeRetryClient(fail_before_success=1, emit_text=True)
    request = MessageRequest(model="deepseek-chat")

    events = [event async for event in client.stream_with_retry(request)]

    assert client.calls == 2
    assert any(isinstance(event, StreamError) for event in events)
    assert any(isinstance(event, StreamDone) for event in events)


def test_pricing_table_estimates_cost() -> None:
    pricing = ModelPricing(input_per_million=1.0, output_per_million=2.0)
    usage = Usage(input_tokens=1000, output_tokens=2000)

    assert pricing.estimate_cost(usage) == pytest.approx(0.005)
    assert PricingTable().get("deepseek-chat") is not None


@pytest.mark.asyncio
async def test_deepseek_client_streams_mock_sse(monkeypatch) -> None:
    events = [
        FakeSSE(json.dumps({"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]})),
        FakeSSE(
            json.dumps(
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            )
        ),
        FakeSSE("[DONE]"),
    ]

    @asynccontextmanager
    async def fake_aconnect_sse(*args, **kwargs):
        yield FakeEventSource(events)

    monkeypatch.setattr("deepseek_tui.client.deepseek.aconnect_sse", fake_aconnect_sse)

    client = DeepSeekClient(api_key="secret")
    request = MessageRequest(model="deepseek-chat")

    streamed = [event async for event in client.stream_chat_completion(request)]

    assert isinstance(streamed[0], StreamTextDelta)
    assert any(isinstance(event, StreamDone) for event in streamed)


def test_deepseek_client_builds_payload_with_system_prompt() -> None:
    client = DeepSeekClient(api_key="secret")
    request = MessageRequest(model="deepseek-chat", system_prompt="system", max_tokens=32)

    payload = client._build_payload(request)

    assert payload["model"] == "deepseek-chat"
    assert payload["max_tokens"] == 32
    assert payload["messages"][0]["role"] == "system"


def test_deepseek_client_builds_openai_tool_schema() -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    client = DeepSeekClient(api_key="secret")
    request = MessageRequest(
        model="deepseek-v4-flash",
        tools=registry.to_api_tools(),
        reasoning_effort="off",
    )

    payload = client._build_payload(request)

    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a UTF-8 text file from disk.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                # Rust extension fields preserved by ToolRegistry.to_api_tools.
                "allowed_callers": ["direct"],
                "defer_loading": False,
            },
        }
    ]
    assert "reasoning_effort" not in payload
    assert "thinking" not in payload
