"""Offline regressions for audit 09; no live service credentials or network."""

import asyncio
import io
import json
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pytest
from PIL import Image

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.client.media import prepare_media_request
from deepseek_tui.client.normalize import drop_orphaned_tool_blocks
from deepseek_tui.client.pricing import _pricing_for_model_at
from deepseek_tui.client.rate_limit import RateLimitRegistry
from deepseek_tui.client.streaming import AnthropicStreamParser, OpenAIStreamParser
from deepseek_tui.config.models import Config, ProviderConfig, VisionConfig
from deepseek_tui.media import import_image, message_images
from deepseek_tui.protocol.messages import (
    Message,
    MessageRequest,
    Role,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    StreamToolCallComplete,
)
from deepseek_tui.tools.encoding import to_api_tool_name


@pytest.mark.parametrize("protocol", ["chat", "anthropic"])
@pytest.mark.parametrize("ending", ["success", "eof", "truncated", "error"])
async def test_adapter_requires_completed_sample(protocol, ending):
    if protocol == "chat":
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "a",
                                    "function": {"name": "read_file", "arguments": '{"path":"x"}'},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
        if ending in ("success", "truncated"):
            chunks.append(
                {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "tool_calls" if ending == "success" else "length",
                        }
                    ]
                }
            )
        if ending == "error":
            chunks.append({"error": {"message": "failed"}})
        body = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
        cls = DeepSeekClient
    else:
        chunks = [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "a", "name": "read_file"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"path":"x"}'},
            },
            {"type": "content_block_stop", "index": 0},
        ]
        if ending == "truncated":
            chunks.append({"type": "message_delta", "delta": {"stop_reason": "max_tokens"}})
        if ending == "error":
            chunks.append({"type": "error", "error": {"message": "failed"}})
        if ending != "eof":
            chunks.append({"type": "message_stop"})
        body = "".join("event: " + c["type"] + "\ndata: " + json.dumps(c) + "\n\n" for c in chunks)
        cls = AnthropicCompatClient
    client = cls(
        api_key="fake",
        base_url="https://example.invalid",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
        ),
    )
    try:
        events = [
            e
            async for e in client.stream_chat_completion(
                MessageRequest(model="fixture", messages=[])
            )
        ]
    finally:
        await client.close()
    calls = [e for e in events if isinstance(e, StreamToolCallComplete)]
    assert bool(calls) == (ending == "success")
    done = [e for e in events if isinstance(e, StreamDone)]
    assert len(done) == 1
    assert done[0].truncated == (ending != "success")
    assert any(isinstance(e, StreamError) for e in events) == (ending in ("eof", "error"))


@pytest.mark.parametrize("cls", [OpenAIStreamParser, AnthropicStreamParser])
def test_empty_eof_is_error_and_finalize_is_idempotent(cls):
    parser = cls()
    events = parser.finalize()
    assert any(isinstance(e, StreamError) for e in events)
    assert not any(isinstance(e, StreamToolCallComplete) for e in events)
    assert parser.finalize() == []


def test_partial_arguments_at_eof_never_repaired_into_a_call():
    parser = OpenAIStreamParser()
    parser.parse_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"name": "write_file", "arguments": '{"path":"x"'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    assert not any(isinstance(e, StreamToolCallComplete) for e in parser.finalize())


async def test_limit_changes_keep_window_history_and_parallel_admissions():
    now = [0.0]
    registry = RateLimitRegistry(clock=lambda: now[0])
    assert (await registry.try_acquire("fake", 1))[0]
    outcomes = await asyncio.gather(*(registry.try_acquire("fake", 3) for _ in range(10)))
    assert sum(ok for ok, _ in outcomes) == 2
    assert not (await registry.try_acquire("fake", 1))[0]
    now[0] = 60.0
    assert (await registry.try_acquire("fake", 1))[0]


@pytest.mark.parametrize("terminal", ["error", "truncated", "missing", "cancel", "success"])
async def test_vision_commits_only_successful_observations(tmp_path, monkeypatch, terminal):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))

    class Stub(LLMClient):
        closed = False

        async def close(self):
            self.closed = True

        async def stream_chat_completion(self, request):
            yield StreamTextDelta(text="observation")
            if terminal == "cancel":
                raise asyncio.CancelledError()
            if terminal == "error":
                yield StreamError(message="failed")
            if terminal in ("truncated", "success"):
                yield StreamDone(truncated=terminal == "truncated")

    stub = Stub()
    cfg = Config(
        vision=VisionConfig(model="visual::fixture"),
        providers={"visual": ProviderConfig(api_key="fake", image_input=True)},
    )
    data = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(data, format="PNG")
    request = MessageRequest(
        model="deepseek-chat",
        messages=[Message.user("question", images=[import_image(data.getvalue())])],
    )
    cache = {}
    with patch("deepseek_tui.client.factory.build_llm_client", return_value=stub):
        if terminal == "success":
            projected = await prepare_media_request(request, cfg, cache)
            assert not any(message_images(m) for m in projected.messages)
            assert cache
        else:
            with pytest.raises(asyncio.CancelledError if terminal == "cancel" else ValueError):
                await prepare_media_request(request, cfg, cache)
            assert not cache
    assert message_images(request.messages[0])
    assert stub.closed


def pair(name="read_file", ids=("a",)):
    return [
        Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="keep")]
            + [ToolUseBlock(id=i, name=name, input={}) for i in ids],
        ),
        Message(
            role=Role.TOOL,
            content=[ToolResultBlock(tool_use_id=i, content="ok") for i in reversed(ids)],
        ),
    ]


@pytest.mark.parametrize(
    "case", ["reversed", "interrupted", "duplicate_use", "duplicate_result", "missing_result"]
)
def test_invalid_tool_rounds_drop_blocks_preserve_text_and_inputs(case):
    history = pair(ids=("a", "b"))
    if case == "reversed":
        history.reverse()
    if case == "interrupted":
        history.insert(1, Message.user("another question"))
    if case == "duplicate_use":
        history[0].content.append(history[0].content[-1].model_copy())
    if case == "duplicate_result":
        history[1].content.append(history[1].content[-1].model_copy())
    if case == "missing_result":
        history[1].content.pop()
    before = [m.model_dump() for m in history]
    clean = drop_orphaned_tool_blocks(history)
    kept_uses = [b.id for m in clean for b in m.content if isinstance(b, ToolUseBlock)]
    kept_results = [
        b.tool_use_id for m in clean for b in m.content if isinstance(b, ToolResultBlock)
    ]
    expected = (
        [] if case in ("reversed", "interrupted") else ["a" if case == "duplicate_use" else "b"]
    )
    assert kept_uses == expected
    assert kept_results == expected
    assert any("keep" in m.text_content() for m in clean)
    assert [m.model_dump() for m in history] == before


def test_valid_parallel_tool_round_is_unchanged():
    history = pair(ids=("a", "b"))
    assert drop_orphaned_tool_blocks(history) is history


@pytest.mark.parametrize("name", ["read_file", "hyphen-name", "mcp:读取"])
def test_names_roundtrip_in_catalog_history_and_internal_forced_choice(name):
    request = MessageRequest(
        model="fixture",
        messages=pair(name),
        tools=[
            {"type": "function", "function": {"name": to_api_tool_name(name), "parameters": {}}}
        ],
        tool_choice={"type": "tool", "name": name},
    )
    a = DeepSeekClient(api_key="fake")._build_payload(request)
    b = AnthropicCompatClient(api_key="fake", base_url="https://example.invalid")._build_payload(
        request
    )
    expected = to_api_tool_name(name)
    assert a["messages"][0]["tool_calls"][0]["function"]["name"] == expected
    assert a["tools"][0]["function"]["name"] == expected
    assert a["tool_choice"]["function"]["name"] == expected
    assert (
        next(x["name"] for x in b["messages"][0]["content"] if x["type"] == "tool_use") == expected
    )
    assert b["tool_choice"]["name"] == expected
    parser = OpenAIStreamParser()
    parser.parse_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "a",
                                "function": {"name": expected, "arguments": "{}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )
    assert (
        next(e.tool_call.name for e in parser.finalize() if isinstance(e, StreamToolCallComplete))
        == name
    )


@pytest.mark.parametrize(
    "model", ["custom-deepseek-future", "deepseek-ai/deepseek-v4-pro", "deepseek-v4-pro-unknown"]
)
def test_unknown_model_is_not_priced(model):
    assert _pricing_for_model_at(model, datetime(2026, 9, 27, tzinfo=timezone.utc)) is None


async def test_midstream_retry_ends_sample_but_prestream_retry_remains():
    class Stub(LLMClient):
        attempts = 0

        async def stream_chat_completion(self, request):
            self.attempts += 1
            if self.attempts == 1:
                raise httpx.ReadError("before content")
            yield StreamTextDelta(text="partial")
            raise httpx.ReadError("after content")

    client = Stub(retry_config=RetryConfig(base_delay=0))
    events = [
        e async for e in client.stream_with_retry(MessageRequest(model="fixture", messages=[]))
    ]
    assert client.attempts == 2
    assert "".join(e.text for e in events if isinstance(e, StreamTextDelta)) == "partial"
    assert isinstance(events[-1], StreamError)
    assert not any(isinstance(e, StreamDone) for e in events)


@pytest.mark.parametrize("protocol", ["chat", "anthropic"])
def test_incomplete_stream_exposes_known_usage_before_error(protocol):
    if protocol == "chat":
        parser = OpenAIStreamParser()
        parser.parse_chunk({"choices": [], "usage": {"prompt_tokens": 42}})
    else:
        parser = AnthropicStreamParser()
        parser.parse_event("message_start", {"message": {"usage": {"input_tokens": 42}}})
    events = parser.finalize()
    assert isinstance(events[0], StreamDone)
    assert events[0].truncated
    assert events[0].usage.input_tokens == 42
    assert isinstance(events[1], StreamError)


@pytest.mark.parametrize(
    "model", ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash", "deepseek-v4-pro"]
)
def test_known_pricing_names_remain_available(model):
    assert _pricing_for_model_at(model, datetime(2026, 9, 27, tzinfo=timezone.utc)) is not None


def test_explicit_pro_pricing_retains_discount_cutover():
    before = _pricing_for_model_at(
        "deepseek-v4-pro", datetime(2026, 5, 31, 15, 59, tzinfo=timezone.utc)
    )
    after = _pricing_for_model_at(
        "deepseek-v4-pro", datetime(2026, 5, 31, 16, 0, tzinfo=timezone.utc)
    )
    assert before.usd.output_per_million < after.usd.output_per_million


def test_wire_shaped_forced_choice_is_not_double_encoded():
    from deepseek_tui.client.anthropic import _map_tool_choice
    from deepseek_tui.client.deepseek import _map_tool_choice_for_chat

    wire = to_api_tool_name("mcp:hyphen-name")
    choice = {"type": "function", "function": {"name": wire}}
    assert _map_tool_choice_for_chat(choice) == choice
    assert _map_tool_choice(choice) == {"type": "tool", "name": wire}
