"""Per-API-key request rate limiting for outbound LLM calls.

A sliding-window log keyed by an API-key fingerprint, shared process-wide
so every caller (main turn, sub-agents, automations,
compaction summaries) draws from the same per-minute budget for a given key.
Calls over the budget fail fast with a ``StreamError`` before any request
leaves the process — the engine surfaces it as a normal stream error.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import deque
from collections.abc import AsyncIterator, Callable

from deepseek_tui.client.base import LLMClient
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamError, StreamEvent

WINDOW_SECONDS = 60.0

Clock = Callable[[], float]


def key_fingerprint(api_key: str) -> str:
    """Short stable identifier for logs/errors — never the raw key."""
    if not api_key:
        return "empty"
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


class RateLimitRegistry:
    """Process-wide sliding-window log: fingerprint → timestamps.

    ``try_acquire`` drops entries older than :data:`WINDOW_SECONDS`, then
    admits the call only when fewer than *limit* calls remain in the window.
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._windows: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._clock = clock or time.monotonic

    async def try_acquire(self, fingerprint: str, limit: int) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_s)``; records the call when allowed."""
        if limit <= 0:
            return True, 0.0
        async with self._lock:
            now = self._clock()
            window = self._windows.get(fingerprint)
            if window is None:
                window = deque(maxlen=limit)
                self._windows[fingerprint] = window
            cutoff = now - WINDOW_SECONDS
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= limit:
                retry_after = max(0.0, window[0] + WINDOW_SECONDS - now)
                return False, retry_after
            window.append(now)
            return True, 0.0

    def reset(self) -> None:
        """Clear all windows (test helper)."""
        self._windows.clear()


_DEFAULT_REGISTRY: RateLimitRegistry | None = None


def default_registry() -> RateLimitRegistry:
    """Process-wide singleton shared by every rate-limited client."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = RateLimitRegistry()
    return _DEFAULT_REGISTRY


class RateLimitedLLMClient(LLMClient):
    """Wrap an LLM client with a per-key per-minute call budget.

    Shares the process-wide registry, so concurrent callers holding
    separate client instances still draw from one budget per key.
    """

    def __init__(
        self,
        inner: LLMClient,
        api_key: str,
        limit: int,
        registry: RateLimitRegistry | None = None,
    ) -> None:
        super().__init__(retry_config=inner.retry_config, api_key=api_key)
        self._inner = inner
        self._fingerprint = key_fingerprint(api_key)
        self._limit = limit
        self._registry = registry or default_registry()

    def cache_fingerprint_units(
        self, request: MessageRequest
    ) -> list[tuple[str, object]]:
        return self._inner.cache_fingerprint_units(request)

    async def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[StreamEvent]:
        allowed, retry_after = await self._registry.try_acquire(
            self._fingerprint, self._limit
        )
        if not allowed:
            yield StreamError(
                message=(
                    f"rate limit exceeded (key {self._fingerprint}, "
                    f"{self._limit}/min): 每分钟调用上限已用尽，"
                    f"约 {retry_after:.0f} 秒后可重试"
                ),
                retryable=False,
            )
            return
        async for event in self._inner.stream_chat_completion(request):
            yield event
