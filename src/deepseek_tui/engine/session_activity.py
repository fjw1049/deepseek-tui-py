"""Session-level activity coordinator — mailbox drain + task polling.

Decouples background work observability from a single parent turn so the TUI
can keep updating after ``TurnComplete`` when tasks or late mailbox events
arrive. Mirrors Rust ``subagent-mailbox-drainer`` + sidebar navigator.

Important: started only from :meth:`Engine.run`, not ``Engine.create``, so
unit tests that construct an engine without a consumer do not spawn a forever
background loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from deepseek_tui.engine.events import (
    SessionActivityEvent,
    SubAgentMailboxEvent,
)
from deepseek_tui.tools.subagent.mailbox import Mailbox

if TYPE_CHECKING:
    from deepseek_tui.engine.engine import Engine

logger = logging.getLogger(__name__)

EmitFn = Callable[..., bool]
PollIntervalSecs = 0.4


class SessionActivityCoordinator:
    """Drain sub-agent mailbox and poll task queue for live UI updates."""

    def __init__(self, engine: Engine, try_emit: EmitFn) -> None:
        self._engine = engine
        self._try_emit = try_emit
        self._cancel = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_subagents = -1
        self._last_tasks = -1

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._cancel.clear()
        self._task = asyncio.create_task(self._run(), name="session-activity")

    async def stop(self) -> None:
        self._cancel.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._task = None

    def _mailbox(self) -> Mailbox | None:
        rt = self._engine.tool_runtime
        if rt is not None and rt.mailbox is not None:
            return rt.mailbox
        mgr = self._engine.tool_context.subagent_manager
        if mgr is not None:
            return mgr.mailbox
        return None

    def _running_subagents(self) -> int:
        mgr = self._engine.tool_context.subagent_manager
        return mgr.running_count() if mgr is not None else 0

    def _running_tasks(self) -> int:
        mgr = self._engine.tool_context.task_manager
        return mgr.running_count() if mgr is not None else 0

    def _emit_activity_snapshot(self, *, force: bool = False) -> None:
        subs = self._running_subagents()
        tasks = self._running_tasks()
        if not force and subs == self._last_subagents and tasks == self._last_tasks:
            return
        self._last_subagents = subs
        self._last_tasks = tasks
        # Skip idle snapshots — nothing useful for UI/tests, avoids queue spam.
        if subs == 0 and tasks == 0:
            return
        parts: list[str] = []
        if subs:
            parts.append(f"{subs} sub-agent(s)")
        if tasks:
            parts.append(f"{tasks} task(s)")
        detail = ", ".join(parts) + " running"
        self._try_emit(
            SessionActivityEvent(
                running_subagents=subs,
                running_tasks=tasks,
                message=detail,
            )
        )

    async def _run(self) -> None:
        mailbox = self._mailbox()
        try:
            while not self._cancel.is_set():
                if mailbox is not None:
                    for envelope in await mailbox.drain_available():
                        self._try_emit(
                            SubAgentMailboxEvent(
                                seq=envelope.seq,
                                message=envelope.message,
                            )
                        )
                self._emit_activity_snapshot()
                try:
                    await asyncio.wait_for(
                        self._cancel.wait(), timeout=PollIntervalSecs
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("session_activity_coordinator_failed")
