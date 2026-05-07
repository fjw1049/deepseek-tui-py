"""SSE (Server-Sent Events) support for streaming responses.

Mirrors the SSE framing used by Rust app-server. Each envelope contains
an ``event:`` field (the tagged-union discriminator) and a ``data:``
field (the payload JSON), terminated by a blank line.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any


def format_sse(payload: dict[str, Any]) -> str:
    """Render one SSE envelope from a plain dict.

    If ``payload['event']`` is present it becomes the ``event:`` field;
    everything else is JSON-encoded under ``data:``.
    """
    event_name = payload.get("event")
    if isinstance(event_name, str) and event_name:
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
    return f"data: {json.dumps(payload)}\n\n"


async def iter_sse(source: AsyncIterable[dict[str, Any]]) -> AsyncIterator[str]:
    """Lift an async iterable of event dicts into SSE-framed strings."""
    async for envelope in source:
        yield format_sse(envelope)


class SseStream:
    """Push-style SSE queue.

    Producer calls :meth:`send` / :meth:`close`. Consumers iterate via
    ``async for chunk in stream:`` — each yielded value is an SSE frame.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._closed = False

    async def send(self, event: dict[str, Any]) -> None:
        if self._closed:
            return
        await self._queue.put(event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield format_sse(event)
