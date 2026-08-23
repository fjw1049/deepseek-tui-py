"""A stream that breaks after emitting content must be replayed, not accepted.

Transport retry (``_should_transparently_retry``) only fires before the first
delta, because a replay would append duplicate deltas onto a buffer that
already holds half a sample. That left the most common long-run failure —
the connection dropping mid-answer — as a terminal ``FAILED`` carrying a
truncated message, which a sub-agent then hands to its parent as the whole
deliverable.

Discarding the partial sample first makes the replay clean, so mid-stream is
retryable on its own budget (the same shape as empty resample).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.engine.turn import (
    MAX_MIDSTREAM_RESAMPLES,
    TurnLoop,
    TurnOutcomeStatus,
    should_resample_midstream,
)
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamEvent,
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
)


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
    async def emit(_event) -> None:
        return None

    return await TurnLoop(client).run(
        request=MessageRequest(
            model="deepseek-chat",
            messages=[Message.user("hi")],
        ),
        emit=emit,
        cancel_event=asyncio.Event(),
        tools=None,
    )


def _assistant_text(result) -> str:
    message = result.assistant_message
    if message is None:
        return ""
    return "".join(b.text for b in message.content if hasattr(b, "text"))


def test_midstream_resample_needs_content_and_a_retryable_error() -> None:
    assert (
        should_resample_midstream(
            any_content_received=True, fired=0, cancelled=False, retryable=True
        )
        is True
    )
    # Nothing streamed yet — that is transparent retry's job, not this one.
    assert (
        should_resample_midstream(
            any_content_received=False, fired=0, cancelled=False, retryable=True
        )
        is False
    )
    assert (
        should_resample_midstream(
            any_content_received=True, fired=0, cancelled=False, retryable=False
        )
        is False
    )
    assert (
        should_resample_midstream(
            any_content_received=True, fired=0, cancelled=True, retryable=True
        )
        is False
    )
    assert (
        should_resample_midstream(
            any_content_received=True,
            fired=MAX_MIDSTREAM_RESAMPLES,
            cancelled=False,
            retryable=True,
        )
        is False
    )


@pytest.mark.asyncio
async def test_break_after_content_replays_without_duplicating_it() -> None:
    client = _ScriptedClient(
        [
            [
                StreamTextDelta(text="半句话就"),
                StreamError(message="connection lost mid-stream", retryable=True),
            ],
            [StreamTextDelta(text="完整的答案"), StreamDone(usage=None)],
        ]
    )
    result = await _run_turn(client)

    assert result.outcome == TurnOutcomeStatus.SUCCESS
    assert client.calls == 2
    # The partial sample is dropped, not prepended to the replay.
    assert _assistant_text(result) == "完整的答案"


@pytest.mark.asyncio
async def test_partial_tool_calls_are_dropped_before_the_replay() -> None:
    """A half-streamed tool call must not survive into the clean sample."""
    client = _ScriptedClient(
        [
            [
                StreamToolCallComplete(
                    tool_call=ToolCall(id="c1", name="read_file", arguments={})
                ),
                StreamError(message="connection lost mid-stream", retryable=True),
            ],
            [
                StreamToolCallComplete(
                    tool_call=ToolCall(id="c2", name="grep_files", arguments={})
                ),
                StreamDone(usage=None),
            ],
        ]
    )
    result = await _run_turn(client)

    assert result.outcome == TurnOutcomeStatus.SUCCESS
    assert [tc.id for tc in result.tool_calls] == ["c2"]


@pytest.mark.asyncio
async def test_exhausted_midstream_budget_fails_the_turn() -> None:
    client = _ScriptedClient(
        [
            [
                StreamTextDelta(text="半句话就"),
                StreamError(message="connection lost mid-stream", retryable=True),
            ]
        ]
    )
    result = await _run_turn(client)

    assert result.outcome == TurnOutcomeStatus.FAILED
    assert client.calls == 1 + MAX_MIDSTREAM_RESAMPLES
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_non_retryable_midstream_error_is_not_replayed() -> None:
    client = _ScriptedClient(
        [
            [
                StreamTextDelta(text="半句话就"),
                StreamError(message="HTTP 401 unauthorized", retryable=False),
            ]
        ]
    )
    result = await _run_turn(client)

    assert result.outcome == TurnOutcomeStatus.FAILED
    assert client.calls == 1
