"""Async broadcast channel — one sender, multiple receivers.

Mirrors Rust ``tokio::sync::broadcast`` semantics with bounded capacity.
Each subscriber gets its own asyncio.Queue; when full, oldest items are
dropped (lagging receiver behaviour).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Generic, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


class AsyncBroadcast(Generic[T]):
    """Simple multi-consumer broadcast channel built on asyncio.Queue."""

    def __init__(self, capacity: int = 1024) -> None:
        self._capacity = capacity
        self._subscribers: set[asyncio.Queue[T]] = set()

    def send(self, item: T) -> int:
        """Broadcast *item* to all subscribers. Returns receivers reached.

        On lagging receivers (queue full) the oldest item is dropped to make
        room and a warn is logged so operators can spot dropped events —
        clients tracking ``since_seq`` cannot otherwise tell they missed any.
        """
        count = 0
        lagged = 0
        dead: list[asyncio.Queue[T]] = []
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
        if lagged:
            logger.warning(
                "broadcast_lag dropped_oldest=%d capacity=%d subscribers=%d",
                lagged,
                self._capacity,
                len(self._subscribers),
            )
        return count

    def subscribe(self) -> asyncio.Queue[T]:
        """Create a new receiver queue and return it."""
        q: asyncio.Queue[T] = asyncio.Queue(maxsize=self._capacity)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[T]) -> None:
        """Remove a receiver queue."""
        self._subscribers.discard(q)

    @property
    def receiver_count(self) -> int:
        return len(self._subscribers)
