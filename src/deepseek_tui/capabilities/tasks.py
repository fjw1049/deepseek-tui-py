"""Task capability adapter for host runtime assembly."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from deepseek_tui.config.models import Config
from deepseek_tui.host.services import ServiceRegistry, ServiceScope
from deepseek_tui.tools.task_manager import (
    ExecutorFunc,
    TaskManager,
    TaskManagerConfig,
    default_tasks_dir,
)

ExecutorFactory = Callable[[], ExecutorFunc]


async def create_task_manager(
    config: Config,
    services: ServiceRegistry,
    *,
    workspace: Path,
    task_data_dir: Path | None,
    shared_task_manager: TaskManager | None,
    executor_factory: ExecutorFactory,
) -> tuple[TaskManager | None, bool]:
    owns_manager = True
    if shared_task_manager is not None:
        manager = shared_task_manager
        owns_manager = False
    elif config.features.tasks:
        data_dir = task_data_dir if task_data_dir is not None else default_tasks_dir()
        task_cfg = TaskManagerConfig(
            data_dir=data_dir,
            default_workspace=workspace,
            allow_shell=config.allow_shell,
            trust_mode=getattr(config, "trust_mode", False),
            worker_count=1,
        )
        manager = TaskManager(task_cfg, executor=executor_factory())
        await manager.start()
    else:
        manager = None

    if manager is not None:
        services.add(TaskManager, manager, owner="tasks", scope=ServiceScope.PROCESS)
    return manager, owns_manager


def attach_task_legacy_bindings(
    manager: TaskManager | None,
    *,
    metadata: dict[str, object],
    services: ServiceRegistry,
) -> None:
    if manager is None:
        return
    metadata["task_manager"] = manager
    if services.optional_named("task_manager") is None:
        services.add_named(
            "task_manager",
            manager,
            owner="tasks",
            scope=ServiceScope.PROCESS,
        )


def attach_task_mcp_bridge(
    manager: TaskManager | None,
    mcp_manager: object | None,
) -> None:
    if manager is not None and mcp_manager is not None:
        manager._shared_mcp_manager = mcp_manager  # noqa: SLF001 — executor reuse


async def shutdown_task_manager(
    manager: TaskManager | None,
    *,
    owns_manager: bool,
) -> None:
    if owns_manager and manager is not None:
        await manager.shutdown()
