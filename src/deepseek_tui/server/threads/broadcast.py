"""Multi-consumer broadcast channel used for runtime SSE fan-out."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Generic, TypeVar

_T = TypeVar("_T")


class BroadcastQueue(asyncio.Queue[_T]):
    lagged: bool = False
    first_dropped: _T | None = None
    predicate: Callable[[_T], bool] | None = None


class AsyncBroadcast(Generic[_T]):
    def __init__(self, capacity: int = 1024) -> None:
        if capacity < 1:
            raise ValueError("Broadcast capacity must be positive")
        self._capacity = capacity
        self._subscribers: set[BroadcastQueue[_T]] = set()

    def send(self, item: _T) -> int:
        count = 0
        for queue in self._subscribers:
            if queue.predicate is not None and not queue.predicate(item):
                continue
            if queue.full():
                dropped = queue.get_nowait()
                if not queue.lagged:
                    queue.first_dropped = dropped
                queue.lagged = True
            queue.put_nowait(item)
            count += 1
        return count

    def subscribe(self) -> BroadcastQueue[_T]:
        queue: BroadcastQueue[_T] = BroadcastQueue(maxsize=self._capacity)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[_T]) -> None:
        self._subscribers.discard(queue)

    @property
    def receiver_count(self) -> int:
        return len(self._subscribers)
