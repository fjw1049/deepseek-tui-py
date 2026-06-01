"""Native L2/L3 pipeline scheduling for smart memory."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from deepseek_tui.memory.native.checkpoint import CheckpointManager
from deepseek_tui.memory.native.l2_scenes import SceneExtractionResult
from deepseek_tui.memory.native.persona_trigger import PersonaTrigger

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryPipelineConfig:
    l2_enabled: bool = True
    l2_delay_after_l1_seconds: float = 90.0
    l2_min_interval_seconds: float = 900.0
    l2_max_interval_seconds: float = 3600.0
    l2_session_active_window_hours: float = 24.0
    l3_persona_interval: int = 50
    l2_retry_delay_seconds: float = 30.0
    l2_max_retries: int = 5
    session_gc_every_notifications: int = 50
    session_gc_inactive_multiplier: float = 3.0


@dataclass(slots=True)
class _L2TimerState:
    fire_at_ms: int
    task: asyncio.Task[None]


class MemoryPipelineManager:
    def __init__(
        self,
        *,
        data_dir: Any,
        config: MemoryPipelineConfig,
        run_l2: Callable[[str, list[dict[str, Any]]], Awaitable[SceneExtractionResult]],
        run_l3: Callable[[str, str | None], Awaitable[None]],
    ) -> None:
        self._checkpoint = CheckpointManager(data_dir)
        self._config = config
        self._run_l2 = run_l2
        self._run_l3 = run_l3
        self._pending_scenes: dict[str, list[dict[str, Any]]] = {}
        self._timers: dict[str, _L2TimerState] = {}
        self._l2_tasks: set[asyncio.Task[None]] = set()
        self._l3_tasks: set[asyncio.Task[None]] = set()
        self._l2_lock = asyncio.Lock()
        self._l3_lock = asyncio.Lock()
        self._l3_pending = False
        self._l2_failures: dict[str, int] = {}
        self._thread_workspaces: dict[str, str] = {}
        self._notify_count = 0
        self._destroyed = False

    def notify_l1_completed(
        self,
        thread_id: str,
        *,
        scenes: list[dict[str, Any]] | None,
        inserted: int,
        workspace: str = "",
    ) -> None:
        if self._destroyed:
            return
        if workspace:
            self._thread_workspaces[thread_id] = workspace
        self._notify_count += 1
        if self._notify_count % max(1, self._config.session_gc_every_notifications) == 0:
            self._gc_cold_sessions()
        self._checkpoint.update_thread(thread_id, l1_processed=max(0, inserted))
        if not self._config.l2_enabled or not scenes:
            return
        self._pending_scenes.setdefault(thread_id, []).extend(scenes)
        self._schedule_l2_after_l1(thread_id)

    def _schedule_l2_after_l1(self, thread_id: str) -> None:
        now = _now_ms()
        checkpoint = self._checkpoint.read()
        state = checkpoint.pipeline_states.get(thread_id)
        last_l2 = state.last_l2_at if state else 0
        delay_fire = now + int(self._config.l2_delay_after_l1_seconds * 1000)
        min_fire = last_l2 + int(self._config.l2_min_interval_seconds * 1000)
        fire_at = max(delay_fire, min_fire)
        self._schedule_l2(thread_id, fire_at)

    def schedule_l2_max_interval(self, thread_id: str) -> None:
        now = _now_ms()
        checkpoint = self._checkpoint.read()
        state = checkpoint.pipeline_states.get(thread_id)
        last_l2 = state.last_l2_at if state else now
        fire_at = last_l2 + int(self._config.l2_max_interval_seconds * 1000)
        self._schedule_l2(thread_id, fire_at)

    def _schedule_l2(self, thread_id: str, fire_at_ms: int) -> None:
        existing = self._timers.get(thread_id)
        if existing is not None and existing.fire_at_ms <= fire_at_ms:
            return
        if existing is not None:
            existing.task.cancel()
        delay = max(0.0, (fire_at_ms - _now_ms()) / 1000)
        task = asyncio.create_task(
            self._l2_timer_fire(thread_id, delay),
            name=f"memory-l2-timer-{thread_id}",
        )
        self._timers[thread_id] = _L2TimerState(fire_at_ms=fire_at_ms, task=task)

    async def _l2_timer_fire(self, thread_id: str, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
            self._timers.pop(thread_id, None)
            if self._session_is_cold(thread_id):
                return
            self._schedule_l2_job(thread_id)
        except asyncio.CancelledError:
            pass

    def _session_is_cold(self, thread_id: str) -> bool:
        checkpoint = self._checkpoint.read()
        state = checkpoint.pipeline_states.get(thread_id)
        if state is None or state.last_active_at <= 0:
            return False
        active_ms = self._config.l2_session_active_window_hours * 60 * 60 * 1000
        return _now_ms() - state.last_active_at > active_ms

    def _schedule_l2_job(self, thread_id: str) -> None:
        task = asyncio.create_task(
            self._run_l2_job(thread_id),
            name=f"memory-l2-{thread_id}",
        )
        self._l2_tasks.add(task)
        task.add_done_callback(self._l2_tasks.discard)

    async def _run_l2_job(self, thread_id: str) -> None:
        async with self._l2_lock:
            scenes = self._pending_scenes.pop(thread_id, [])
            if not scenes:
                return
            try:
                result = await self._run_l2(thread_id, scenes)
            except Exception:
                logger.exception("memory_l2_job_failed thread_id=%s", thread_id)
                failures = self._l2_failures.get(thread_id, 0) + 1
                self._l2_failures[thread_id] = failures
                if failures <= self._config.l2_max_retries:
                    self._pending_scenes.setdefault(thread_id, []).extend(scenes)
                    self._schedule_l2(
                        thread_id,
                        _now_ms() + int(self._config.l2_retry_delay_seconds * 1000),
                    )
                else:
                    logger.error(
                        "memory_l2_job_dropped_after_retries thread_id=%s retries=%d",
                        thread_id,
                        failures,
                    )
                return
            self._l2_failures.pop(thread_id, None)
            self._checkpoint.mark_l2_completed(
                thread_id,
                scenes_processed=result.scenes_processed,
                latest_cursor=result.latest_cursor,
                persona_update_reason=result.persona_update_reason,
            )
            self.schedule_l2_max_interval(thread_id)
            self._maybe_schedule_l3(thread_id)

    def _maybe_schedule_l3(self, thread_id: str) -> None:
        workspace = self._thread_workspaces.get(thread_id)
        trigger = PersonaTrigger(
            self._checkpoint.path.parent.parent,
            interval=self._config.l3_persona_interval,
            workspace=workspace,
        )
        result = trigger.should_generate()
        if not result.should:
            return
        if self._l3_pending:
            return
        self._l3_pending = True
        task = asyncio.create_task(
            self._run_l3_job(result.reason, workspace),
            name=f"memory-l3-{thread_id}",
        )
        self._l3_tasks.add(task)
        task.add_done_callback(self._l3_tasks.discard)

    async def _run_l3_job(self, reason: str, workspace: str | None) -> None:
        async with self._l3_lock:
            self._l3_pending = False
            try:
                await self._run_l3(reason, workspace)
            except Exception:
                logger.exception("memory_l3_job_failed")
                return
            self._checkpoint.mark_persona_generated()

    async def flush_session(self, thread_id: str) -> None:
        timer = self._timers.pop(thread_id, None)
        if timer is not None:
            timer.task.cancel()
        if self._pending_scenes.get(thread_id):
            await self._run_l2_job(thread_id)
        pending = [
            task
            for task in list(self._l2_tasks)
            if not task.done() and task.get_name() == f"memory-l2-{thread_id}"
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._l3_tasks:
            await asyncio.gather(*list(self._l3_tasks), return_exceptions=True)

    def _gc_cold_sessions(self) -> None:
        checkpoint = self._checkpoint.read()
        active_ms = (
            self._config.l2_session_active_window_hours
            * self._config.session_gc_inactive_multiplier
            * 60
            * 60
            * 1000
        )
        cutoff = _now_ms() - active_ms
        cold = [
            thread_id
            for thread_id, state in checkpoint.pipeline_states.items()
            if state.last_active_at and state.last_active_at < cutoff
        ]
        for thread_id in cold:
            timer = self._timers.pop(thread_id, None)
            if timer is not None:
                timer.task.cancel()
            self._pending_scenes.pop(thread_id, None)
            self._l2_failures.pop(thread_id, None)
            checkpoint.pipeline_states.pop(thread_id, None)
        if cold:
            self._checkpoint.write(checkpoint)

    async def stop(self) -> None:
        self._destroyed = True
        for timer in self._timers.values():
            timer.task.cancel()
        self._timers.clear()
        tasks = list(self._l2_tasks | self._l3_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._l2_tasks.clear()
        self._l3_tasks.clear()


def _now_ms() -> int:
    return int(time.time() * 1000)
