"""Thinking mode and forced tool_choice are mutually exclusive.

Thinking-capable endpoints (DeepSeek official among them) reject the
combination with HTTP 400 "Thinking mode does not support this tool_choice".
The caller forcing a tool call wants the structured output, so the tool call
wins and the thinking fields are dropped — for every model and host served
by this client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.protocol.responses import StreamEvent


def _client() -> DeepSeekClient:
    return DeepSeekClient(api_key="test", thinking_supported=True)


def _request(**overrides: object) -> MessageRequest:
    base: dict = {
        "model": "deepseek-v4-flash",
        "messages": [Message.user("hi")],
        "reasoning_effort": "low",
    }
    base.update(overrides)
    return MessageRequest(**base)


def test_forced_named_tool_choice_drops_thinking() -> None:
    payload = _client()._build_payload(
        _request(tool_choice={"type": "tool", "name": "narration_emit"})
    )
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "narration_emit"},
    }
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload


def test_required_tool_choice_drops_thinking() -> None:
    payload = _client()._build_payload(_request(tool_choice="required"))
    assert payload["tool_choice"] == "required"
    assert "thinking" not in payload


def test_auto_tool_choice_keeps_thinking() -> None:
    payload = _client()._build_payload(_request(tool_choice={"type": "auto"}))
    assert payload["tool_choice"] == "auto"
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "low"


def test_no_tool_choice_keeps_thinking() -> None:
    payload = _client()._build_payload(_request())
    assert "tool_choice" not in payload
    assert payload["thinking"] == {"type": "enabled"}


class _CaptureClient(DeepSeekClient):
    """Capture the MessageRequest that narration sends; return a tool call."""

    def __init__(self) -> None:
        super().__init__(api_key="test", thinking_supported=True)
        self.captured: MessageRequest | None = None

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        from deepseek_tui.protocol.responses import (
            StreamToolCallComplete,
            ToolCall,
        )

        self.captured = request
        yield StreamToolCallComplete(
            tool_call=ToolCall(
                id="t1",
                name="narration_emit",
                arguments={"publish": True, "finding": "ok", "next_goal": ""},
            )
        )


@pytest.mark.asyncio
async def test_narration_request_disables_thinking() -> None:
    """Narration must be safe on thinking-capable endpoints of any provider."""
    from deepseek_tui.server.phase_bridge import (
        IntentBundle,
        compute_narration_plan,
    )

    client = _CaptureClient()
    bundle = IntentBundle(
        user_goal="goal",
        phase="explore",
        confirmed_facts=(),
        working_hypothesis=(),
        next_intent="read files",
        batch_intent="read files",
        locale="zh",
    )
    plan = await compute_narration_plan(
        client, model="deepseek-v4-flash", bundle=bundle, timeout_s=5.0
    )
    assert plan is not None and plan.publish
    assert client.captured is not None
    assert client.captured.reasoning_effort == "off"
    assert client.captured.tool_choice == {
        "type": "tool",
        "name": "narration_emit",
    }
