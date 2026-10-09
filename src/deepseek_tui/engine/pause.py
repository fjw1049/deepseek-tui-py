"""Cooperative task suspension, shared with descendant agents.

Pausing fences new work. Already dispatched external effects are not rolled back.
Only model requests are cancelled; tool results are allowed to settle.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

T = TypeVar("T")


class RunPause:
    def __init__(self) -> None:
        self.requested = asyncio.Event()
        self.released = asyncio.Event()
        self.released.set()
        self.generation = 0
        self.running_tools = 0

    @contextmanager
    def tool_execution(self) -> Iterator[None]:
        self.running_tools += 1
        try:
            yield
        finally:
            self.running_tools -= 1

    @property
    def paused(self) -> bool:
        return self.requested.is_set()

    def pause(self) -> None:
        if not self.paused:
            self.generation += 1
            self.released.clear()
            self.requested.set()

    def resume(self) -> None:
        self.requested.clear()
        self.released.set()

    async def wait(self, cancel: asyncio.Event) -> None:
        while self.paused:
            released = asyncio.create_task(self.released.wait())
            cancelled = asyncio.create_task(cancel.wait())
            try:
                await asyncio.wait({released, cancelled}, return_when=asyncio.FIRST_COMPLETED)
                if cancel.is_set():
                    raise asyncio.CancelledError
            finally:
                for task in (released, cancelled):
                    task.cancel()
                await asyncio.gather(released, cancelled, return_exceptions=True)
        if cancel.is_set():
            raise asyncio.CancelledError

    async def model_request(
        self, start: Callable[[], Awaitable[T]], cancel: asyncio.Event,
    ) -> T | None:
        """Discard a model generation interrupted by takeover, retaining its turn."""
        await self.wait(cancel)
        generation = self.generation
        request = asyncio.ensure_future(start())
        paused = asyncio.create_task(self.requested.wait())
        try:
            await asyncio.wait({request, paused}, return_when=asyncio.FIRST_COMPLETED)
            if self.paused or generation != self.generation:
                return None
            return await request
        finally:
            request.cancel()
            paused.cancel()
            await asyncio.gather(request, paused, return_exceptions=True)

    async def wait_active_timeout(self, event: asyncio.Event, timeout: float,
                                  cancel: asyncio.Event) -> None:
        """Wait for an event, excluding time spent under human control."""
        remaining = timeout
        while not event.is_set():
            await self.wait(cancel)
            started = asyncio.get_running_loop().time()
            done = asyncio.create_task(event.wait())
            paused = asyncio.create_task(self.requested.wait())
            try:
                finished, _ = await asyncio.wait(
                    {done, paused}, timeout=max(0, remaining),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not finished:
                    raise TimeoutError
            finally:
                remaining -= asyncio.get_running_loop().time() - started
                done.cancel()
                paused.cancel()
                await asyncio.gather(done, paused, return_exceptions=True)
