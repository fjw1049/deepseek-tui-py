"""Automation capability adapter for host runtime assembly."""

from __future__ import annotations

import asyncio
from pathlib import Path

from deepseek_tui.config.models import Config
from deepseek_tui.host.services import ServiceRegistry, ServiceScope
from deepseek_tui.tools.automation_manager import AutomationManager, default_automations_dir
from deepseek_tui.tools.automation_scheduler import (
    AutomationSchedulerConfig,
    run_scheduler_loop,
)
from deepseek_tui.tools.automation_tools import AUTOMATION_MANAGER_KEY
from deepseek_tui.tools.task_manager import TaskManager


async def create_automation_runtime(
    config: Config,
    services: ServiceRegistry,
    *,
    task_manager: TaskManager | None,
    automation_data_dir: Path | None,
    automation_tick_interval_secs: float,
) -> tuple[AutomationManager | None, asyncio.Event | None, asyncio.Task[None] | None]:
    if not config.features.automations:
        return None, None, None
    if not config.features.tasks:
        raise ValueError(
            "features.automations requires features.tasks=True "
            "(automations fire by enqueueing tasks)"
        )
    assert task_manager is not None
    automation_root = (
        automation_data_dir
        if automation_data_dir is not None
        else default_automations_dir()
    )
    manager = AutomationManager.open(automation_root)
    services.add(
        AutomationManager,
        manager,
        owner="automation",
        scope=ServiceScope.PROCESS,
    )
    cancel = asyncio.Event()
    task = asyncio.create_task(
        run_scheduler_loop(
            manager,
            task_manager,
            cancel,
            AutomationSchedulerConfig(
                tick_interval_secs=automation_tick_interval_secs,
            ),
        ),
        name="automation-scheduler",
    )
    return manager, cancel, task


async def stop_automation_runtime(
    cancel: asyncio.Event | None,
    scheduler_task: asyncio.Task[None] | None,
    *,
    timeout_s: float = 5.0,
) -> None:
    if cancel is not None:
        cancel.set()
    if scheduler_task is None:
        return
    try:
        await asyncio.wait_for(scheduler_task, timeout=timeout_s)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        scheduler_task.cancel()
    except Exception:  # noqa: BLE001
        pass


def attach_automation_legacy_bindings(
    manager: AutomationManager | None,
    *,
    metadata: dict[str, object],
    services: ServiceRegistry,
) -> None:
    if manager is None:
        return
    metadata[AUTOMATION_MANAGER_KEY] = manager
    services.add_named(
        AUTOMATION_MANAGER_KEY,
        manager,
        owner="automation",
        scope=ServiceScope.PROCESS,
    )
