"""Empty successful streams are resampled after StreamDone, not mid-stream.

Transport retry (``_should_transparently_retry``) treats thinking as content
so a half-emitted stream is never replayed. Empty resample is the next
layer: the stream finished, but there is no visible text and no tool call.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.engine.events import TextDeltaEvent, ThinkingDeltaEvent
from deepseek_tui.engine.turn import (
    MAX_EMPTY_RESPONSE_RESAMPLES,
    EmptyResponseReason,
    TurnLoop,
    TurnOutcomeStatus,
    empty_response_reason,
    should_resample_empty,
)
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamEvent,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
    ToolCall,
)


@pytest.mark.parametrize(
    ("text", "thinking", "tools", "expected"),
    [
        ("hello", "", 0, None),
        ("hello", "thoughts", 0, None),
        ("", "", 1, None),
        ("", "thoughts", 1, None),
        ("  \n", "", 0, EmptyResponseReason.NO_VISIBLE_CONTENT),
        ("", "", 0, EmptyResponseReason.NO_VISIBLE_CONTENT),
        ("", "only thinking", 0, EmptyResponseReason.REASONING_ONLY),
        ("   ", "only thinking", 0, EmptyResponseReason.REASONING_ONLY),
    ],
)
def test_empty_response_reason(text, thinking, tools, expected) -> None:
    assert (
        empty_response_reason(text=text, thinking=thinking, tool_call_count=tools)
        == expected
    )


def test_empty_resample_budget_is_independent_of_transport() -> None:
    reason = EmptyResponseReason.REASONING_ONLY
    assert should_resample_empty(reason, fired=0, cancelled=False) is True
    assert (
        should_resample_empty(
            reason, fired=MAX_EMPTY_RESPONSE_RESAMPLES, cancelled=False
        )
        is False
    )
    assert should_resample_empty(reason, fired=0, cancelled=True) is False
    assert should_resample_empty(None, fired=0, cancelled=False) is False


class _ScriptedClient(LLMClient):
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self.scripts = scripts
        self.calls = 0

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        script = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        for event in script:
            yield event


async def _run_turn(client: LLMClient):
    events = []

    async def emit(event):
        events.append(event)

    result = await TurnLoop(client).run(
        request=MessageRequest(
            model="deepseek-chat",
            messages=[Message.user("hi")],
        ),
        emit=emit,
        cancel_event=asyncio.Event(),
        tools=None,
    )
    return result, events


def _assistant_text(result) -> str:
    message = result.assistant_message
    if message is None:
        return ""
    return "".join(b.text for b in message.content if hasattr(b, "text"))


@pytest.mark.asyncio
async def test_reasoning_only_is_resampled_then_keeps_the_useful_sample() -> None:
    client = _ScriptedClient(
        [
            [StreamThinkingDelta(thinking="ponder"), StreamDone(usage=None)],
            [StreamTextDelta(text="answer"), StreamDone(usage=None)],
        ]
    )
    result, events = await _run_turn(client)
    assert result.outcome == TurnOutcomeStatus.SUCCESS
    assert client.calls == 2
    assert _assistant_text(result) == "answer"
    # First-attempt thinking was already streamed; the persisted message is
    # only the useful sample.
    assert any(isinstance(e, ThinkingDeltaEvent) for e in events)
    assert any(isinstance(e, TextDeltaEvent) and e.text == "answer" for e in events)


@pytest.mark.asyncio
async def test_blank_success_is_resampled() -> None:
    client = _ScriptedClient(
        [
            [StreamDone(usage=None)],
            [StreamTextDelta(text="recovered"), StreamDone(usage=None)],
        ]
    )
    result, _ = await _run_turn(client)
    assert result.outcome == TurnOutcomeStatus.SUCCESS
    assert client.calls == 2
    assert _assistant_text(result) == "recovered"


@pytest.mark.asyncio
async def test_empty_resample_accepts_the_last_attempt() -> None:
    client = _ScriptedClient([[StreamDone(usage=None)]])
    result, _ = await _run_turn(client)
    assert result.outcome == TurnOutcomeStatus.SUCCESS
    assert client.calls == 1 + MAX_EMPTY_RESPONSE_RESAMPLES
    assert result.assistant_message is None


@pytest.mark.asyncio
async def test_tool_call_without_text_is_not_empty() -> None:
    client = _ScriptedClient(
        [
            [
                StreamToolCallComplete(
                    tool_call=ToolCall(id="c1", name="read_file", arguments={})
                ),
                StreamDone(usage=None),
            ]
        ]
    )
    result, _ = await _run_turn(client)
    assert result.outcome == TurnOutcomeStatus.SUCCESS
    assert client.calls == 1
    assert len(result.tool_calls) == 1


@pytest.mark.asyncio
async def test_visible_text_is_not_resampled() -> None:
    client = _ScriptedClient(
        [[StreamTextDelta(text="ok"), StreamDone(usage=None)]]
    )
    result, _ = await _run_turn(client)
    assert result.outcome == TurnOutcomeStatus.SUCCESS
    assert client.calls == 1
