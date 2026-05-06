from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from deepseek_tui.engine.events import EngineEvent
from deepseek_tui.engine.ops import CancelRequestOp, EngineOp, SendMessageOp


class EngineHandle:
    def __init__(self) -> None:
        self._op_queue: asyncio.Queue[EngineOp] = asyncio.Queue()
        self._event_queue: asyncio.Queue[EngineEvent] = asyncio.Queue()
        self.cancel_event = asyncio.Event()

    async def send_message(
        self,
        content: str,
        model: str | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> None:
        await self.send_op(
            SendMessageOp(
                content=content,
                model=model,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
        )

    async def send_op(self, op: EngineOp) -> None:
        await self._op_queue.put(op)

    async def next_op(self) -> EngineOp:
        return await self._op_queue.get()

    async def emit(self, event: EngineEvent) -> None:
        await self._event_queue.put(event)

    async def events(self) -> AsyncIterator[EngineEvent]:
        while True:
            yield await self._event_queue.get()

    async def cancel(self, reason: str = "user_cancelled") -> None:
        self.cancel_event.set()
        await self.send_op(CancelRequestOp(reason=reason))

    def reset_cancel(self) -> None:
        self.cancel_event = asyncio.Event()
