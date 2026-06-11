from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deepseek_tui.capabilities.automation import (
    attach_automation_bindings,
    create_automation_runtime,
    stop_automation_runtime,
)
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.tools.automation_manager import AutomationManager
from deepseek_tui.tools.automation_tools import AUTOMATION_MANAGER_KEY
from deepseek_tui.tools.task_manager import (
    ExecutionTask,
    TaskExecutionResult,
    TaskManager,
    TaskManagerConfig,
)


async def _fake_executor(
    _task: ExecutionTask,
    _cancel: asyncio.Event,
) -> TaskExecutionResult:
    return TaskExecutionResult(summary="ok")


def _task_manager(tmp_path: Path) -> TaskManager:
    return TaskManager(
        TaskManagerConfig(
            data_dir=tmp_path / "tasks",
            default_workspace=tmp_path,
            worker_count=1,
        ),
        executor=_fake_executor,
    )


@pytest.mark.asyncio
async def test_automation_capability_skips_when_disabled(tmp_path: Path) -> None:
    services = ServiceRegistry()

    manager, cancel, task = await create_automation_runtime(
        Config(features=FeatureConfig(automations=False)),
        services,
        task_manager=_task_manager(tmp_path),
        automation_data_dir=tmp_path / "automations",
        automation_tick_interval_secs=60.0,
    )

    assert manager is None
    assert cancel is None
    assert task is None
    assert services.optional(AutomationManager) is None


@pytest.mark.asyncio
async def test_automation_capability_requires_tasks(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(features=FeatureConfig(tasks=False, automations=True))

    with pytest.raises(ValueError, match="requires features.tasks"):
        await create_automation_runtime(
            cfg,
            services,
            task_manager=None,
            automation_data_dir=tmp_path / "automations",
            automation_tick_interval_secs=60.0,
        )


@pytest.mark.asyncio
async def test_automation_capability_starts_scheduler_and_binds_legacy(
    tmp_path: Path,
) -> None:
    services = ServiceRegistry()
    metadata: dict[str, object] = {}
    task_manager = _task_manager(tmp_path)

    manager, cancel, task = await create_automation_runtime(
        Config(features=FeatureConfig(tasks=True, automations=True)),
        services,
        task_manager=task_manager,
        automation_data_dir=tmp_path / "automations",
        automation_tick_interval_secs=60.0,
    )
    try:
        assert manager is not None
        assert cancel is not None
        assert task is not None
        assert task.get_name() == "automation-scheduler"
        assert services.require(AutomationManager) is manager

        attach_automation_bindings(manager, services=services)

        assert AUTOMATION_MANAGER_KEY not in metadata
        assert services.require_named(AUTOMATION_MANAGER_KEY) is manager
    finally:
        await stop_automation_runtime(cancel, task, timeout_s=2.0)


@pytest.mark.asyncio
async def test_automation_capability_stops_scheduler(tmp_path: Path) -> None:
    services = ServiceRegistry()
    task_manager = _task_manager(tmp_path)
    manager, cancel, task = await create_automation_runtime(
        Config(features=FeatureConfig(tasks=True, automations=True)),
        services,
        task_manager=task_manager,
        automation_data_dir=tmp_path / "automations",
        automation_tick_interval_secs=60.0,
    )

    await stop_automation_runtime(cancel, task, timeout_s=2.0)

    assert manager is not None
    assert cancel is not None and cancel.is_set()
    assert task is not None and task.done()
