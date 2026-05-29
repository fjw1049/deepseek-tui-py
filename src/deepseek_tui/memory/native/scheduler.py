"""Per-thread L1 extraction scheduling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _ThreadScheduleState:
    conversation_count: int = 0
    pending_messages: list[dict[str, Any]] = field(default_factory=list)
    idle_task: asyncio.Task[None] | None = None


class L1Scheduler:
    def __init__(
        self,
        *,
        every_n: int,
        idle_timeout_s: float,
        run_extraction: Callable[
            [str, list[dict[str, Any]]], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self._every_n = max(1, every_n)
        self._idle_timeout_s = idle_timeout_s
        self._run_extraction = run_extraction
        self._states: dict[str, _ThreadScheduleState] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _state(self, thread_id: str) -> _ThreadScheduleState:
        if thread_id not in self._states:
            self._states[thread_id] = _ThreadScheduleState()
        return self._states[thread_id]

    def notify_messages(self, thread_id: str, messages: list[dict[str, Any]]) -> None:
        if not messages:
            return
        state = self._state(thread_id)
        state.pending_messages.extend(messages)
        state.conversation_count += 1
        if state.conversation_count >= self._every_n:
            self._schedule_job(thread_id, state.pending_messages.copy())
            state.pending_messages.clear()
            state.conversation_count = 0
            if state.idle_task is not None:
                state.idle_task.cancel()
                state.idle_task = None
            return
        if state.idle_task is not None:
            state.idle_task.cancel()
        state.idle_task = asyncio.create_task(
            self._idle_fire(thread_id),
            name=f"l1-idle-{thread_id}",
        )

    async def _idle_fire(self, thread_id: str) -> None:
        try:
            await asyncio.sleep(self._idle_timeout_s)
            state = self._state(thread_id)
            if not state.pending_messages:
                return
            batch = state.pending_messages.copy()
            state.pending_messages.clear()
            state.conversation_count = 0
            self._schedule_job(thread_id, batch)
        except asyncio.CancelledError:
            pass

    def _schedule_job(self, thread_id: str, batch: list[dict[str, Any]]) -> None:
        task = asyncio.create_task(
            self._run_job(thread_id, batch),
            name=f"l1-extract-{thread_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_job(self, thread_id: str, batch: list[dict[str, Any]]) -> None:
        try:
            await self._run_extraction(thread_id, batch)
        except Exception:
            logger.exception("l1_scheduled_job_failed thread_id=%s", thread_id)

    async def flush_session(self, thread_id: str) -> None:
        state = self._states.get(thread_id)
        if state is None:
            return
        if state.idle_task is not None:
            state.idle_task.cancel()
            state.idle_task = None
        if state.pending_messages:
            batch = state.pending_messages.copy()
            state.pending_messages.clear()
            state.conversation_count = 0
            await self._run_extraction(thread_id, batch)

    async def stop(self) -> None:
        for state in self._states.values():
            if state.idle_task is not None:
                state.idle_task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        self._states.clear()
        self._tasks.clear()
