"""A client error fails identically on every retry; only transient statuses are retried."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.engine.events import ErrorEvent
from deepseek_tui.engine.turn import TurnLoop, TurnOutcomeStatus
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamEvent, StreamTextDelta


class _StatusClient(LLMClient):
    """Fails with ``status`` on the first call, then answers."""

    def __init__(self, status: int) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self.status = status
        self.calls = 0

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        if self.calls == 1:
            url = "https://api.example.test/v1/chat/completions"
            raise httpx.HTTPStatusError(
                f"HTTP {self.status} from {url}: error",
                request=httpx.Request("POST", url),
                response=httpx.Response(self.status),
            )
        yield StreamTextDelta(text="ok")
        yield StreamDone()


async def _run(client: LLMClient):
    events = []

    async def emit(event) -> None:
        events.append(event)

    result = await TurnLoop(client).run(
        request=MessageRequest(model="deepseek-chat", messages=[Message.user("hi")]),
        emit=emit,
        cancel_event=asyncio.Event(),
        tools=None,
    )
    return result, events


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
async def test_client_error_fails_without_retry(status):
    client = _StatusClient(status)
    result, events = await _run(client)
    assert client.calls == 1
    assert result.outcome == TurnOutcomeStatus.FAILED
    assert f"HTTP {status}" in result.error_message
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    # The real cause is shown once, never masked as a stream interruption.
    assert [e.retryable for e in errors] == [False]
    assert f"HTTP {status}" in errors[0].message


@pytest.mark.parametrize("status", [408, 429, 500, 503, 529])
async def test_transient_status_is_still_retried(status):
    client = _StatusClient(status)
    result, _ = await _run(client)
    assert client.calls == 2
    assert result.outcome == TurnOutcomeStatus.SUCCESS


async def test_exhausted_balance_names_the_cause():
    from deepseek_tui.client.deepseek import DeepSeekClient

    client = DeepSeekClient(
        api_key="fake",
        base_url="https://example.invalid",
        transport=httpx.MockTransport(lambda r: httpx.Response(
            402, json={"error": {"message": "Insufficient Balance"}})),
    )
    try:
        with pytest.raises(httpx.HTTPStatusError, match="balance or quota"):
            async for _ in client.stream_chat_completion(
                MessageRequest(model="deepseek-chat", messages=[Message.user("hi")])
            ):
                pass
    finally:
        await client.close()
