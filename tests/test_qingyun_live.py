"""Live compatibility matrix for Qingyun-hosted Claude models.

Run with ``QINGYUN_API_KEY`` set explicitly::

    pytest -q -m live tests/test_qingyun_live.py -s
"""

from __future__ import annotations

import os

import pytest

from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    StreamToolCallComplete,
)

BASE_URL = "https://api.qingyuntop.top"
MODELS = (
    "claude-sonnet-4-6",
    "claude-opus-4-5-20251101",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-6",
)
TOOL = {
    "type": "function",
    "function": {
        "name": "compat_probe",
        "description": "Return the requested probe value",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    },
}

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


async def _collect(client, request: MessageRequest):
    text: list[str] = []
    calls = []
    done = False
    async for event in client.stream_chat_completion(request):
        if isinstance(event, StreamTextDelta):
            text.append(event.text)
        elif isinstance(event, StreamToolCallComplete):
            calls.append(event.tool_call)
        elif isinstance(event, StreamDone):
            done = True
    return "".join(text), calls, done


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("protocol", ("openai", "anthropic"))
async def test_text_and_tool_compatibility(model: str, protocol: str) -> None:
    api_key = os.environ.get("QINGYUN_API_KEY", "")
    if not api_key:
        pytest.skip("QINGYUN_API_KEY is not configured")
    client = (
        AnthropicCompatClient(api_key, BASE_URL, timeout_seconds=45)
        if protocol == "anthropic"
        else DeepSeekClient(api_key, BASE_URL, timeout_seconds=45)
    )
    try:
        text, _, done = await _collect(
            client,
            MessageRequest(
                model=model,
                messages=[Message.user("Reply exactly MODEL_OK")],
                max_tokens=64,
            ),
        )
        assert done
        assert "MODEL_OK" in text

        _, calls, done = await _collect(
            client,
            MessageRequest(
                model=model,
                messages=[
                    Message.user("Call compat_probe with value MODEL_TOOL_OK")
                ],
                tools=[TOOL],
                tool_choice="required",
                max_tokens=128,
            ),
        )
        assert done
        assert len(calls) == 1
        assert calls[0].name == "compat_probe"
        assert calls[0].arguments.get("value") == "MODEL_TOOL_OK"
    finally:
        await client.close()
