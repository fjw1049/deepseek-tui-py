from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from deepseek_tui.engine.events import EngineEvent
from deepseek_tui.engine.ops import CancelRequestOp, EngineOp, SendMessageOp


class EngineHandle:
    def __init__(self) -> None:
        self._op_queue: asyncio.Queue[EngineOp] = asyncio.Queue()
        self._event_queue: asyncio.Queue[EngineEvent] = asyncio.Queue()
        self.cancel_event = asyncio.Event()
        self.pending_user_inputs: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._steer_queue: asyncio.Queue[str] = asyncio.Queue()

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

    async def steer(self, text: str) -> None:
        """Inject a user message mid-turn (mirrors Rust rx_steer)."""
        await self._steer_queue.put(text)

    def drain_steers(self) -> list[str]:
        """Non-blocking drain of all queued steer messages."""
        steers: list[str] = []
        while True:
            try:
                steers.append(self._steer_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return steers

    def resolve_user_input(self, tool_call_id: str, response: dict[str, Any]) -> bool:
        """Resolve a pending user input request from the TUI.

        Returns True if the future was found and resolved.
        """
        future = self.pending_user_inputs.get(tool_call_id)
        if future is not None and not future.done():
            future.set_result(response)
            return True
        return False
