from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from deepseek_tui.engine.usage_ledger import TurnUsageLedger

from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamEvent,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
    StreamToolCallDelta,
)


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_transparent_retries: int = 2
    max_error_retries: int = 5
    base_delay: float = 0.2
    max_delay: float = 10.0

    def transparent_delay(self, attempt: int) -> float:
        return float(min(self.base_delay * (2**attempt), self.max_delay))

    def error_delay(self, attempt: int) -> float:
        return float(min(self.base_delay * (2**attempt), self.max_delay))


class LLMClient(ABC):
    def __init__(self, retry_config: RetryConfig | None = None) -> None:
        self.retry_config = retry_config or RetryConfig()

    @abstractmethod
    def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError

    async def stream_with_retry(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        transparent_retries = 0
        error_retries = 0
        content_received = False

        while True:
            try:
                async for event in self.stream_chat_completion(request):
                    if isinstance(
                        event,
                        (
                            StreamTextDelta,
                            StreamThinkingDelta,
                            StreamToolCallDelta,
                            StreamToolCallComplete,
                        ),
                    ):
                        content_received = True
                    yield event
                return
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if (
                    not content_received
                    and transparent_retries < self.retry_config.max_transparent_retries
                ):
                    transparent_retries += 1
                    await asyncio.sleep(self.retry_config.transparent_delay(transparent_retries))
                    continue
                if content_received and error_retries < self.retry_config.max_error_retries:
                    error_retries += 1
                    yield StreamError(message=str(exc), retryable=True)
                    await asyncio.sleep(self.retry_config.error_delay(error_retries))
                    continue
                raise


class MeteredLLMClient(LLMClient):
    """Wrap an LLM client and record ``StreamDone`` usage into a turn ledger.

    Records exactly one ledger line per streamed request — the *last*
    usage-bearing ``StreamDone`` — so a parser or provider that emits more
    than one done event cannot double-bill the turn.
    """

    def __init__(
        self,
        inner: LLMClient,
        ledger: "TurnUsageLedger",
    ) -> None:
        super().__init__(retry_config=inner.retry_config)
        self._inner = inner
        self._ledger = ledger

    async def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        from deepseek_tui.engine.usage_ledger import current_usage_source

        last_usage = None
        # Captured alongside the usage: the finally block may run after the
        # caller's ``usage_source(...)`` scope has already been reset.
        source: str | None = None
        try:
            async for event in self._inner.stream_chat_completion(request):
                if isinstance(event, StreamDone) and event.usage is not None:
                    last_usage = event.usage
                    source = current_usage_source()
                yield event
        finally:
            if last_usage is not None:
                self._ledger.add(
                    model=request.model,
                    source=source or "unknown",
                    usage=last_usage,
                )
