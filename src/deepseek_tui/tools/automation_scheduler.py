"""Background scheduler for :class:`AutomationManager`.

Mirrors Rust ``automation_manager.rs::spawn_scheduler`` (817-850).

The loop ticks the manager + reconciles run statuses on a fixed
cadence. Failures inside a single tick are logged and swallowed so a
transient error never kills the scheduler — the next tick gets a fresh
chance.

Q1 decision (Engine-level): one scheduler task per ``Engine`` instance,
started in ``Engine.create`` and cancelled in ``Engine.shutdown``.

Q2 decision: tick interval defaults to 15 s (matches Rust
``AutomationSchedulerConfig::default``), with a 5-second floor for
sanity. Tests can pass ``tick_interval_secs=1`` for fast iteration.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.tools.automation_manager import AutomationManager
    from deepseek_tui.tools.task_manager import TaskManager

__all__ = [
    "AutomationSchedulerConfig",
    "run_scheduler_loop",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AutomationSchedulerConfig:
    """Mirrors Rust ``AutomationSchedulerConfig`` (805-815).

    The ``tick_interval_secs`` floor of 5 matches the Rust ``.max(5)``
    clamp at line 827.
    """

    tick_interval_secs: float = 15.0


async def run_scheduler_loop(
    manager: AutomationManager,
    task_manager: TaskManager,
    cancel: asyncio.Event,
    config: AutomationSchedulerConfig | None = None,
) -> None:
    """Run the automation scheduler until ``cancel`` is set.

    Each iteration:

    1. ``manager.scheduler_tick(task_manager)`` — fire any due automations.
    2. ``manager.reconcile_run_statuses(task_manager)`` — copy task
       statuses back into runs.
    3. Sleep up to ``tick_interval_secs`` or wake early on cancel.

    Exceptions in tick/reconcile are logged at warning level and
    swallowed (Rust does the same with ``tracing::warn!`` — see
    automation_manager.rs:836, 839).
    """
    cfg = config or AutomationSchedulerConfig()
    interval = max(5.0, float(cfg.tick_interval_secs))

    logger.info(
        "automation_scheduler_start interval_secs=%.1f", interval
    )

    while not cancel.is_set():
        try:
            await manager.scheduler_tick(task_manager)
        except Exception as exc:  # noqa: BLE001 — never kill the loop
            logger.warning("automation_scheduler_tick_failed: %s", exc)

        try:
            await manager.reconcile_run_statuses(task_manager)
        except Exception as exc:  # noqa: BLE001
            logger.warning("automation_scheduler_reconcile_failed: %s", exc)

        # Sleep until the next tick OR until cancel fires, whichever is
        # first. ``asyncio.wait`` here mirrors Rust ``tokio::select!``
        # at line 843.
        try:
            await asyncio.wait_for(cancel.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue

    logger.info("automation_scheduler_stop")
