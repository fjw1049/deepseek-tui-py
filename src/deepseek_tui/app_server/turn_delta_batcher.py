"""Coalesce streaming ``item.delta`` events before persistence / SSE."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

EmitDelta = Callable[[str, str, str, str, dict[str, Any]], Awaitable[None]]

FLUSH_INTERVAL_S = 0.05


class TurnDeltaBatcher:
    """Buffer text deltas and flush on a fixed interval or when forced."""

    __slots__ = ("_emit", "_buffers", "_flush_lock", "_flush_task", "_thread_id", "_turn_id")

    def __init__(
        self,
        thread_id: str,
        turn_id: str,
        emit: EmitDelta,
    ) -> None:
        self._thread_id = thread_id
        self._turn_id = turn_id
        self._emit = emit
        self._buffers: dict[tuple[str, str], str] = {}
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()

    async def append(
        self,
        item_id: str,
        kind: str,
        delta_text: str,
    ) -> None:
        if not delta_text:
            return
        key = (item_id, kind)
        self._buffers[key] = self._buffers.get(key, "") + delta_text
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(
                self._delayed_flush(),
                name=f"delta-flush-{self._turn_id}",
            )

    async def _delayed_flush(self) -> None:
        try:
            await asyncio.sleep(FLUSH_INTERVAL_S)
        except asyncio.CancelledError:
            raise
        finally:
            # Clear before flush(): flush() cancels _flush_task when set, and
            # awaiting the current task from inside itself raises
            # ``RuntimeError: await wasn't used with future``.
            self._flush_task = None
        await self.flush()

    async def flush(self) -> int:
        async with self._flush_lock:
            task = self._flush_task
            current = asyncio.current_task()
            if task is not None and not task.done() and task is not current:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._flush_task = None

            emitted = 0
            pending = self._buffers
            self._buffers = {}
            for (item_id, kind), text in pending.items():
                if not text:
                    continue
                await self._emit(
                    self._thread_id,
                    self._turn_id,
                    item_id,
                    kind,
                    {"delta": text, "kind": kind},
                )
                emitted += 1
            return emitted
