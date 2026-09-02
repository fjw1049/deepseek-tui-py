"""Rate limiter tests: sliding window, key isolation, concurrency, wrapper."""

from __future__ import annotations

import asyncio

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.client.rate_limit import (
    WINDOW_SECONDS,
    RateLimitedLLMClient,
    RateLimitRegistry,
    key_fingerprint,
)
from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamError, StreamTextDelta


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StubClient(LLMClient):
    """Minimal client recording how many streams it actually served."""

    def __init__(
        self,
        api_key: str = "test-key",
        events: tuple = (StreamTextDelta(text="ok"),),
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self._events = events
        self.calls = 0

    async def stream_chat_completion(self, request: MessageRequest):
        self.calls += 1
        for event in self._events:
            yield event


def _request() -> MessageRequest:
    return MessageRequest(model="deepseek-v4-pro", messages=[])


async def test_window_allows_up_to_limit_then_rejects() -> None:
    registry = RateLimitRegistry(clock=FakeClock())
    fp = key_fingerprint("sk-a")
    for _ in range(3):
        allowed, _ = await registry.try_acquire(fp, 3)
        assert allowed
    allowed, retry_after = await registry.try_acquire(fp, 3)
    assert not allowed
    assert 0 < retry_after <= WINDOW_SECONDS


async def test_window_resets_after_window_seconds() -> None:
    clock = FakeClock()
    registry = RateLimitRegistry(clock=clock)
    fp = key_fingerprint("sk-a")
    for _ in range(3):
        await registry.try_acquire(fp, 3)
    assert not (await registry.try_acquire(fp, 3))[0]
    clock.advance(WINDOW_SECONDS)
    allowed, _ = await registry.try_acquire(fp, 3)
    assert allowed


async def test_window_is_sliding_not_fixed() -> None:
    clock = FakeClock(start=0.0)
    registry = RateLimitRegistry(clock=clock)
    fp = key_fingerprint("sk-a")
    await registry.try_acquire(fp, 2)  # t=0
    clock.advance(10)
    await registry.try_acquire(fp, 2)  # t=10
    clock.advance(55)  # t=65: entry at t=0 expired, entry at t=10 still inside
    allowed, _ = await registry.try_acquire(fp, 2)
    assert allowed
    allowed, _ = await registry.try_acquire(fp, 2)
    assert not allowed


async def test_keys_are_isolated() -> None:
    registry = RateLimitRegistry(clock=FakeClock())
    a, b = key_fingerprint("sk-a"), key_fingerprint("sk-b")
    for _ in range(2):
        await registry.try_acquire(a, 2)
    assert not (await registry.try_acquire(a, 2))[0]
    allowed, _ = await registry.try_acquire(b, 2)
    assert allowed


async def test_concurrent_acquires_never_exceed_limit() -> None:
    registry = RateLimitRegistry(clock=FakeClock())
    fp = key_fingerprint("sk-a")
    results = await asyncio.gather(*(registry.try_acquire(fp, 5) for _ in range(20)))
    allowed = sum(1 for ok, _ in results if ok)
    assert allowed == 5


async def test_zero_limit_disables_limiting() -> None:
    registry = RateLimitRegistry(clock=FakeClock())
    fp = key_fingerprint("sk-a")
    for _ in range(10):
        allowed, _ = await registry.try_acquire(fp, 0)
        assert allowed


async def test_wrapper_passes_through_events_within_budget() -> None:
    inner = StubClient(events=(StreamTextDelta(text="hi"), StreamTextDelta(text="!")))
    wrapper = RateLimitedLLMClient(
        inner,
        api_key="sk-a",
        limit=2,
        registry=RateLimitRegistry(clock=FakeClock()),
    )
    events = [e async for e in wrapper.stream_chat_completion(_request())]
    assert all(isinstance(e, StreamTextDelta) for e in events)
    assert inner.calls == 1


async def test_wrapper_rejects_over_budget_without_calling_inner() -> None:
    inner = StubClient()
    wrapper = RateLimitedLLMClient(
        inner,
        api_key="sk-a",
        limit=1,
        registry=RateLimitRegistry(clock=FakeClock()),
    )
    first = [e async for e in wrapper.stream_chat_completion(_request())]
    assert isinstance(first[0], StreamTextDelta)
    second = [e async for e in wrapper.stream_chat_completion(_request())]
    assert len(second) == 1
    err = second[0]
    assert isinstance(err, StreamError)
    assert err.retryable is False
    assert key_fingerprint("sk-a") in err.message
    assert inner.calls == 1


def test_wrapper_exposes_api_key() -> None:
    inner = StubClient(api_key="sk-a")
    wrapper = RateLimitedLLMClient(inner, api_key="sk-a", limit=1)
    assert wrapper.api_key == "sk-a"


def test_factory_wraps_client_when_rate_limit_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hermetic key resolution: skip env so the provider config
    # api_key is used, regardless of the developer machine's real secrets.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = Config(
        provider="deepseek",
        providers={"deepseek": ProviderConfig(api_key="test-key", rate_limit=10)},
    )
    client = build_llm_client(config)
    assert isinstance(client, RateLimitedLLMClient)
    assert client.api_key == "test-key"


def test_factory_returns_plain_client_without_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = Config(
        provider="deepseek",
        providers={"deepseek": ProviderConfig(api_key="test-key")},
    )
    client = build_llm_client(config)
    assert not isinstance(client, RateLimitedLLMClient)
