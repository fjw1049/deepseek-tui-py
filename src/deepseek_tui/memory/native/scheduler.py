"""Per-thread L1 extraction scheduling — wraps PeriodicTurnScheduler when warmup off."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.post_turn.scheduler import PeriodicTurnScheduler

logger = logging.getLogger(__name__)


@dataclass
class _ThreadScheduleState:
    conversation_count: int = 0
    pending_messages: list[dict[str, Any]] = field(default_factory=list)
    idle_task: asyncio.Task[None] | None = None
    warmup_threshold: int = 1
    l1_running: bool = False


class L1Scheduler:
    def __init__(
        self,
        *,
        every_n: int,
        idle_timeout_s: float,
        warmup_enabled: bool = True,
        run_extraction: Callable[
            [str, list[dict[str, Any]]], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self._every_n = max(1, every_n)
        self._idle_timeout_s = idle_timeout_s
        self._warmup_enabled = warmup_enabled
        self._run_extraction = run_extraction
        self._states: dict[str, _ThreadScheduleState] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._periodic = PeriodicTurnScheduler(
            every_n=self._every_n,
            idle_timeout_s=self._idle_timeout_s,
            warmup_enabled=False,
        )

    def _state(self, thread_id: str) -> _ThreadScheduleState:
        if thread_id not in self._states:
            warmup_threshold = 1 if self._warmup_enabled and self._every_n > 1 else 0
            self._states[thread_id] = _ThreadScheduleState(
                warmup_threshold=warmup_threshold
            )
        return self._states[thread_id]

    def _effective_threshold(self, state: _ThreadScheduleState) -> int:
        if not self._warmup_enabled:
            return self._every_n
        if state.warmup_threshold <= 0:
            return self._every_n
        return min(state.warmup_threshold, self._every_n)

    def _advance_warmup(self, state: _ThreadScheduleState) -> None:
        if not self._warmup_enabled or state.warmup_threshold <= 0:
            return
        next_threshold = state.warmup_threshold * 2
        if next_threshold >= self._every_n:
            state.warmup_threshold = 0
        else:
            state.warmup_threshold = next_threshold

    def _count_due(self, thread_id: str, state: _ThreadScheduleState) -> bool:
        if not self._warmup_enabled:
            self._periodic.notify(thread_id, None)
            if self._periodic.is_due(thread_id):
                self._periodic.reset(thread_id)
                return True
            return False
        state.conversation_count += 1
        return state.conversation_count >= self._effective_threshold(state)

    def _reset_count(self, thread_id: str, state: _ThreadScheduleState) -> None:
        if self._warmup_enabled:
            state.conversation_count = 0
            self._advance_warmup(state)
        else:
            self._periodic.reset(thread_id)

    def notify_messages(self, thread_id: str, messages: list[dict[str, Any]]) -> None:
        if not messages:
            return
        state = self._state(thread_id)
        state.pending_messages.extend(messages)
        if self._count_due(thread_id, state):
            batch = state.pending_messages.copy()
            state.pending_messages.clear()
            self._reset_count(thread_id, state)
            if state.idle_task is not None:
                state.idle_task.cancel()
                state.idle_task = None
            scheduled = self._schedule_job(thread_id, batch)
            if not scheduled:
                state.idle_task = asyncio.create_task(
                    self._idle_fire(thread_id),
                    name=f"l1-idle-{thread_id}",
                )
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
            self._reset_count(thread_id, state)
            scheduled = self._schedule_job(thread_id, batch)
            if not scheduled:
                state.idle_task = asyncio.create_task(
                    self._idle_fire(thread_id),
                    name=f"l1-idle-{thread_id}",
                )
        except asyncio.CancelledError:
            pass

    def _schedule_job(self, thread_id: str, batch: list[dict[str, Any]]) -> bool:
        state = self._state(thread_id)
        if state.l1_running:
            state.pending_messages[:0] = batch
            return False
        state.l1_running = True
        task = asyncio.create_task(
            self._run_job(thread_id, batch),
            name=f"l1-extract-{thread_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _run_job(self, thread_id: str, batch: list[dict[str, Any]]) -> None:
        try:
            await self._run_extraction(thread_id, batch)
        except Exception:
            logger.exception("l1_scheduled_job_failed thread_id=%s", thread_id)
        finally:
            state = self._states.get(thread_id)
            if state is not None:
                state.l1_running = False

    async def _drain_thread_jobs(self, thread_id: str) -> None:
        pending = [
            task
            for task in list(self._tasks)
            if not task.done() and task.get_name() == f"l1-extract-{thread_id}"
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def flush_session(self, thread_id: str) -> None:
        state = self._states.get(thread_id)
        if state is None:
            return
        if state.idle_task is not None:
            state.idle_task.cancel()
            state.idle_task = None
        await self._drain_thread_jobs(thread_id)
        if state.pending_messages:
            batch = state.pending_messages.copy()
            state.pending_messages.clear()
            self._reset_count(thread_id, state)
            state.l1_running = True
            try:
                await self._run_extraction(thread_id, batch)
            finally:
                state.l1_running = False

    async def stop(self) -> None:
        for state in self._states.values():
            if state.idle_task is not None:
                state.idle_task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        self._states.clear()
        self._tasks.clear()
