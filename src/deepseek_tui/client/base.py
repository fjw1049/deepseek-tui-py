from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from deepseek_tui.engine.usage_ledger import TurnUsageLedger

import logging

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

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_transparent_retries: int = 2
    max_error_retries: int = 5
    base_delay: float = 0.2
    max_delay: float = 10.0
    # Fraction of the backoff to spread each delay by. Sub-agents run
    # concurrently against one provider, so without jitter a shared 429 or 5xx
    # makes them all back off and retry in lockstep, reproducing the burst that
    # caused it. Multiplicative, so a zero delay stays zero.
    jitter: float = 0.25

    def _spread(self, delay: float) -> float:
        if delay <= 0.0 or self.jitter <= 0.0:
            return delay
        return delay * (1.0 + random.uniform(-self.jitter, self.jitter))

    def delay(self, attempt: int) -> float:
        return self._spread(min(self.base_delay * (2**attempt), self.max_delay))


class LLMClient(ABC):
    def __init__(
        self,
        retry_config: RetryConfig | None = None,
        *,
        api_key: str = "",
        base_url: str = "",
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.retry_config = retry_config or RetryConfig()
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.extra_headers = dict(extra_headers or {})
        self._http_client: httpx.AsyncClient | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return a persistent httpx client for connection reuse.

        ``read=None`` lets the per-chunk ``asyncio.wait_for`` in the
        subclass stream methods be the sole source of truth for SSE idle
        timeouts. With a finite httpx ``read`` the global timer can fire
        first and surface as ``httpx.ReadTimeout`` instead of
        ``asyncio.TimeoutError``, hitting different retry branches in
        ``TurnLoop.run`` and confusing transparent-retry
        accounting. Connect/write timeouts stay bounded so DNS or TLS
        stalls still surface promptly.
        """
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self.timeout_seconds,
                    write=self.timeout_seconds,
                    read=None,
                    pool=self.timeout_seconds,
                ),
                transport=self.transport,
            )
        return self._http_client

    async def close(self) -> None:
        """Close the persistent HTTP client."""
        if self._http_client is not None and not self._http_client.is_closed:
            logger.debug("http_client_close base_url=%s", self.base_url)
            await self._http_client.aclose()
            self._http_client = None

    @abstractmethod
    def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError

    def cache_fingerprint_units(
        self, request: MessageRequest
    ) -> list[tuple[str, object]]:
        """Return ordered, cache-relevant units as this client sends them.

        Concrete protocol clients override this when they transform messages
        or tools. The fallback keeps custom/testing clients useful.
        """
        units: list[tuple[str, object]] = [
            ("model", request.model),
            (
                "tools",
                {"tools": request.tools or [], "tool_choice": request.tool_choice},
            ),
            ("system", request.system_prompt or ""),
        ]
        units.extend(
            (
                f"message[{index}] role={message.role.value}",
                [block.model_dump() for block in message.content],
            )
            for index, message in enumerate(request.messages)
        )
        return units

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
                    await asyncio.sleep(self.retry_config.delay(transparent_retries))
                    continue
                if content_received and error_retries < self.retry_config.max_error_retries:
                    error_retries += 1
                    yield StreamError(message=str(exc), retryable=True)
                    await asyncio.sleep(self.retry_config.delay(error_retries))
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
        ledger: TurnUsageLedger,
    ) -> None:
        super().__init__(retry_config=inner.retry_config)
        self._inner = inner
        self._ledger = ledger

    def cache_fingerprint_units(
        self, request: MessageRequest
    ) -> list[tuple[str, object]]:
        return self._inner.cache_fingerprint_units(request)

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
