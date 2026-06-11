from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deepseek_tui.capabilities.tasks import (
    attach_task_legacy_bindings,
    attach_task_mcp_bridge,
    create_task_manager,
    shutdown_task_manager,
)
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.host.services import ServiceRegistry, ServiceScope
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


class _ShutdownRecorder:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.mark.asyncio
async def test_task_capability_skips_when_disabled(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(features=FeatureConfig(tasks=False))

    manager, owns = await create_task_manager(
        cfg,
        services,
        workspace=tmp_path,
        task_data_dir=tmp_path / "tasks",
        shared_task_manager=None,
        executor_factory=lambda: _fake_executor,
    )

    assert manager is None
    assert owns is True
    assert services.optional(TaskManager) is None


@pytest.mark.asyncio
async def test_task_capability_uses_shared_manager_without_ownership(tmp_path: Path) -> None:
    services = ServiceRegistry()
    shared = _task_manager(tmp_path)
    cfg = Config(features=FeatureConfig(tasks=False))

    manager, owns = await create_task_manager(
        cfg,
        services,
        workspace=tmp_path,
        task_data_dir=tmp_path / "tasks",
        shared_task_manager=shared,
        executor_factory=lambda: _fake_executor,
    )

    assert manager is shared
    assert owns is False
    assert services.require(TaskManager) is shared


@pytest.mark.asyncio
async def test_task_capability_creates_and_starts_owned_manager(tmp_path: Path) -> None:
    services = ServiceRegistry()
    cfg = Config(features=FeatureConfig(tasks=True))

    manager, owns = await create_task_manager(
        cfg,
        services,
        workspace=tmp_path,
        task_data_dir=tmp_path / "tasks",
        shared_task_manager=None,
        executor_factory=lambda: _fake_executor,
    )
    try:
        assert manager is not None
        assert owns is True
        assert services.require(TaskManager) is manager
        assert manager._cfg.data_dir == tmp_path / "tasks"  # noqa: SLF001
        assert manager._cfg.default_workspace == tmp_path  # noqa: SLF001
    finally:
        if manager is not None:
            await manager.shutdown()


def test_task_capability_registers_legacy_bindings(tmp_path: Path) -> None:
    services = ServiceRegistry()
    metadata: dict[str, object] = {}
    manager = _task_manager(tmp_path)
    services.add(TaskManager, manager, owner="tasks", scope=ServiceScope.PROCESS)

    attach_task_legacy_bindings(manager, metadata=metadata, services=services)

    assert metadata["task_manager"] is manager
    assert services.require_named("task_manager") is manager


def test_task_capability_attaches_mcp_bridge(tmp_path: Path) -> None:
    manager = _task_manager(tmp_path)
    mcp = object()

    attach_task_mcp_bridge(manager, mcp)

    assert manager._shared_mcp_manager is mcp  # noqa: SLF001


@pytest.mark.asyncio
async def test_task_capability_shutdown_respects_ownership() -> None:
    manager = _ShutdownRecorder()

    await shutdown_task_manager(manager, owns_manager=False)  # type: ignore[arg-type]
    assert manager.shutdown_calls == 0

    await shutdown_task_manager(manager, owns_manager=True)  # type: ignore[arg-type]
    assert manager.shutdown_calls == 1
