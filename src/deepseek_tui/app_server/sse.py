"""SSE (Server-Sent Events) support for streaming responses."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


class SseStream:
    """SSE stream for sending events to clients."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def send(self, event: dict[str, Any]) -> None:
        """Send an event to the stream."""
        await self._queue.put(event)

    async def close(self) -> None:
        """Close the stream."""
        await self._queue.put(None)

    async def __aiter__(self) -> AsyncIterator[str]:
        """Iterate over SSE-formatted events."""
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"
