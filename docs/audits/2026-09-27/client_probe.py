"""Audit 09 characterization: local synthetic inputs, no network or real credentials.
Run: PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/client_probe.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
from PIL import Image

from deepseek_tui.client.anthropic import AnthropicCompatClient, _build_anthropic_messages
from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.client.media import prepare_media_request
from deepseek_tui.client.normalize import drop_orphaned_tool_blocks
from deepseek_tui.client.pricing import _pricing_for_model_at
from deepseek_tui.client.rate_limit import RateLimitRegistry
from deepseek_tui.client.streaming import OpenAIStreamParser
from deepseek_tui.config.models import Config, ProviderConfig, VisionConfig
from deepseek_tui.media import import_image, message_images
from deepseek_tui.protocol.messages import (
    Message,
    MessageRequest,
    Role,
    ToolResultBlock,
    ToolUseBlock,
)
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    StreamToolCallComplete,
)


class InterruptedClient(LLMClient):
    def __init__(self):
        super().__init__(retry_config=RetryConfig(base_delay=0, max_error_retries=1))
        self.attempts = 0

    async def stream_chat_completion(self, request):
        self.attempts += 1
        yield StreamTextDelta(text="partial" if self.attempts == 1 else "complete")
        if self.attempts == 1:
            raise httpx.ReadError("synthetic interruption")
        yield StreamDone()


class VisionStub(LLMClient):
    def __init__(self, terminal):
        super().__init__()
        self.terminal = terminal

    async def stream_chat_completion(self, request):
        yield StreamTextDelta(text="Partial observation")
        yield self.terminal


async def main():
    results = {}
    registry = RateLimitRegistry(clock=lambda: 0)
    accepted = [await registry.try_acquire("fake-key", limit) for limit in [1, 3, 3, 3, 3, 3]]
    results["same_window_admissions_after_limit_1_to_3"] = sum(ok for ok, _ in accepted)

    # Exercise actual HTTP adapters against MockTransport, ending SSE without terminal markers.
    bodies = {
        DeepSeekClient: 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-a","function":{"name":"write_file","arguments":"{\\"path\\":\\"x\\""}}]}}]}\n\n',
        AnthropicCompatClient: "\n\n".join(
            [
                'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"call-a","name":"write_file"}}',
                'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"x\\""}}',
            ]
        )
        + "\n\n",
    }
    for client_type, body in bodies.items():
        transport = httpx.MockTransport(
            lambda request, body=body: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, text=body
            )
        )
        client = client_type(
            api_key="fake", base_url="https://example.invalid", transport=transport
        )
        try:
            events = [
                event
                async for event in client.stream_chat_completion(
                    MessageRequest(model="fixture", messages=[Message.user("fixture")])
                )
            ]
        finally:
            await client.close()
        results[client_type.__name__ + "_eof"] = {
            "completed_arguments": [
                e.tool_call.arguments for e in events if isinstance(e, StreamToolCallComplete)
            ],
            "done_truncated": [e.truncated for e in events if isinstance(e, StreamDone)],
            "errors": sum(isinstance(e, StreamError) for e in events),
        }
    parser = OpenAIStreamParser()
    results["openai_repeated_finalize_done_count"] = sum(
        isinstance(e, StreamDone) for e in parser.finalize() + parser.finalize()
    )

    cfg = Config(
        vision=VisionConfig(model="visual::image-model"),
        providers={
            "visual": ProviderConfig(
                api_key="fake", base_url="https://example.invalid", image_input=True
            )
        },
    )
    data = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(data, format="PNG")
    request = MessageRequest(
        model="deepseek-chat",
        messages=[Message.user("Color?", images=[import_image(data.getvalue())])],
    )
    for label, terminal in [
        ("error", StreamError(message="failed")),
        ("truncated", StreamDone(truncated=True)),
    ]:
        cache = {}
        with patch(
            "deepseek_tui.client.factory.build_llm_client", return_value=VisionStub(terminal)
        ):
            projected = await prepare_media_request(request, cfg, cache)
        results["vision_partial_" + label] = {
            "cached": bool(cache),
            "images_left": sum(len(message_images(m)) for m in projected.messages),
        }

    history = [
        Message(role=Role.TOOL, content=[ToolResultBlock(tool_use_id="same", content="result")]),
        Message(
            role=Role.ASSISTANT,
            content=[ToolUseBlock(id="same", name="read_file", input={"path": "x"})],
        ),
    ]
    results["out_of_order_history_returned_unchanged"] = (
        drop_orphaned_tool_blocks(history) is history
    )
    results["anthropic_out_of_order_wire_roles"] = [
        m["role"] for m in _build_anthropic_messages(history, system_prompt=None)[1]
    ]
    results["unknown_deepseek_model_has_price"] = (
        _pricing_for_model_at("custom-deepseek-future", datetime(2026, 9, 27, tzinfo=timezone.utc))
        is not None
    )
    from deepseek_tui.tools.encoding import to_api_tool_name

    internal_name = "mcp:读取"
    paired = [
        Message(
            role=Role.ASSISTANT, content=[ToolUseBlock(id="named", name=internal_name, input={})]
        ),
        Message(role=Role.TOOL, content=[ToolResultBlock(tool_use_id="named", content="ok")]),
    ]
    named_request = MessageRequest(
        model="fixture",
        messages=paired,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": to_api_tool_name(internal_name),
                    "parameters": {"type": "object"},
                },
            }
        ],
    )
    chat_payload = DeepSeekClient(api_key="fake")._build_payload(named_request)
    anthropic_payload = AnthropicCompatClient(
        api_key="fake", base_url="https://example.invalid"
    )._build_payload(named_request)
    results["tool_name_projection"] = {
        "schema": chat_payload["tools"][0]["function"]["name"],
        "chat_history": chat_payload["messages"][0]["tool_calls"][0]["function"]["name"],
        "anthropic_history": anthropic_payload["messages"][0]["content"][0]["name"],
    }
    replay = InterruptedClient()
    events = [
        e async for e in replay.stream_with_retry(MessageRequest(model="fixture", messages=[]))
    ]
    results["base_retry_text_if_consumer_continues_after_error"] = "".join(
        e.text for e in events if isinstance(e, StreamTextDelta)
    )
    return results


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="audit09-") as home:
        with patch.dict(os.environ, {"DEEPSEEK_HOME": home}):
            print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
