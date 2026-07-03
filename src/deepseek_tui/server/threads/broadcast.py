"""Multi-consumer broadcast channel used for runtime SSE fan-out."""

from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

_T = TypeVar("_T")


class AsyncBroadcast(Generic[_T]):
    """Simple multi-consumer broadcast channel built on asyncio.Queue."""

    def __init__(self, capacity: int = 1024) -> None:
        self._capacity = capacity
        self._subscribers: set[asyncio.Queue[_T]] = set()

    def send(self, item: _T) -> int:
        count = 0
        lagged = 0
        dead: list[asyncio.Queue[_T]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(item)
                count += 1
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(item)
                    count += 1
                    lagged += 1
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    dead.append(q)
        for q in dead:
            self._subscribers.discard(q)
        return count

    def subscribe(self) -> asyncio.Queue[_T]:
        q: asyncio.Queue[_T] = asyncio.Queue(maxsize=self._capacity)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[_T]) -> None:
        self._subscribers.discard(q)

    @property
    def receiver_count(self) -> int:
        return len(self._subscribers)
