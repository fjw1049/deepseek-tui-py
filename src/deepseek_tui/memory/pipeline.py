"""Memory pipeline — L0→L3 orchestration, scheduling, agent loop.

Consolidates native/pipeline.py, scheduler.py, agent_loop.py.
Native L2/L3 pipeline scheduling for smart memory.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from deepseek_tui.memory.store import CheckpointManager

from typing import TYPE_CHECKING as _TC_PIPE
if _TC_PIPE:
    from deepseek_tui.memory.l2 import SceneExtractionResult
    from deepseek_tui.memory.l3 import PersonaTrigger

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
        from deepseek_tui.memory.l3 import PersonaTrigger
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


# ======================================================================
# From native/scheduler.py
# ======================================================================

# Per-thread L1 extraction scheduling — wraps PeriodicTurnScheduler when warmup off.

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
        self._periodic_counts: dict[str, int] = {}

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
            count = self._periodic_counts.get(thread_id, 0) + 1
            self._periodic_counts[thread_id] = count
            if count >= self._every_n:
                self._periodic_counts[thread_id] = 0
                return True
            return False
        state.conversation_count += 1
        return state.conversation_count >= self._effective_threshold(state)

    def _reset_count(self, thread_id: str, state: _ThreadScheduleState) -> None:
        if self._warmup_enabled:
            state.conversation_count = 0
            self._advance_warmup(state)
        else:
            self._periodic_counts[thread_id] = 0

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


# ======================================================================
# From native/agent_loop.py
# ======================================================================

# Headless tool-call loop for memory pipeline agents.

import inspect
from dataclasses import dataclass, field

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.tools import has_tool_call_markers, parse_tool_calls
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
)
from deepseek_tui.tools.registry import ToolError
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.registry import ToolRegistry


@dataclass(slots=True)
class MemorySubagentLoopResult:
    final_text: str = ""
    steps: int = 0
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)
    tool_results: list[tuple[str, dict, str]] = field(default_factory=list)


async def run_memory_subagent_loop(
    client: LLMClient,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    registry: ToolRegistry,
    context: ToolContext,
    max_steps: int = 8,
    max_tokens: int = 4096,
) -> MemorySubagentLoopResult:
    """Run a restricted, headless tool loop for memory background agents.

    This mirrors the useful core of the sub-agent loop without user-visible
    agent lifecycle state. Callers are expected to pass a narrow registry and a
    sandboxed ``ToolContext`` rooted at the memory workspace, e.g. scene_blocks.
    """
    registry.set_context(context)
    api_tools = registry.to_api_tools()
    messages = [Message.user(user_prompt)]
    final_text = ""
    errors: list[str] = []
    tool_results: list[tuple[str, dict, str]] = []
    total_tool_calls = 0

    for step in range(1, max(1, max_steps) + 1):
        chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        request = MessageRequest(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            tools=api_tools,
            tool_choice={"type": "auto"} if api_tools else None,
            max_tokens=max_tokens,
        )
        stream = client.stream_with_retry(request)
        if not hasattr(stream, "__aiter__"):
            if inspect.isawaitable(stream):
                await stream
            return MemorySubagentLoopResult(
                final_text=final_text,
                steps=step - 1,
                tool_calls=total_tool_calls,
                errors=["client did not return an async event stream"],
                tool_results=tool_results,
            )
        async for event in stream:
            if isinstance(event, StreamTextDelta):
                chunks.append(event.text)
            elif isinstance(event, StreamToolCallComplete):
                tool_calls.append(event.tool_call)

        text = "".join(chunks).strip()
        if not tool_calls and text and has_tool_call_markers(text):
            parsed = parse_tool_calls(text)
            text = parsed.clean_text.strip()
            for call in parsed.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=call.id,
                        name=call.name,
                        arguments=dict(call.args) if call.args else {},
                    )
                )

        if text:
            final_text = text
            messages.append(Message.assistant(text))
        if not tool_calls:
            return MemorySubagentLoopResult(
                final_text=final_text,
                steps=step,
                tool_calls=total_tool_calls,
                errors=errors,
                tool_results=tool_results,
            )

        total_tool_calls += len(tool_calls)
        messages.append(
            Message.assistant_with_tools(
                [
                    ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments)
                    for tc in tool_calls
                ]
            )
        )
        for tool_call in tool_calls:
            output, is_error = await _execute_memory_tool(registry, context, tool_call)
            args = (
                dict(tool_call.arguments)
                if isinstance(tool_call.arguments, dict)
                else {}
            )
            tool_results.append((tool_call.name, args, output))
            if is_error:
                errors.append(output)
            messages.append(Message.tool_result(tool_call.id, output, is_error=is_error))

    return MemorySubagentLoopResult(
        final_text=final_text,
        steps=max_steps,
        tool_calls=total_tool_calls,
        errors=errors,
        tool_results=tool_results,
    )


async def _execute_memory_tool(
    registry: ToolRegistry,
    context: ToolContext,
    tool_call: ToolCall,
) -> tuple[str, bool]:
    try:
        result = await registry.execute(tool_call.name, tool_call.arguments, context)
    except ToolError as exc:
        return f"Error: {exc}", True
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}: {exc}", True
    if not result.success:
        return f"Error: {result.content}", True
    return result.content, False
