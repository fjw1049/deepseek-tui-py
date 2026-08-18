"""Forked threads do not inherit the current goal."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.goal.service import GoalService
from deepseek_tui.server.threads.manager import RuntimeThreadManager
from deepseek_tui.server.threads.models import CreateThreadRequest, RuntimeThreadManagerConfig


@pytest.fixture
def manager(tmp_path: Path) -> RuntimeThreadManager:
    config = Config(
        features=FeatureConfig(
            mcp=False,
            tasks=False,
            subagents=False,
            automations=False,
        ),
    )
    return RuntimeThreadManager(
        config=config,
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig(
            data_dir=tmp_path / "runtime",
            task_data_dir=tmp_path / "tasks",
        ),
    )


@pytest.mark.asyncio
async def test_fork_does_not_copy_goal(manager: RuntimeThreadManager) -> None:
    thread = await manager.create_thread(CreateThreadRequest(workspace=str(manager.workspace)))
    service = GoalService()
    service.create("Do not copy this")
    service.enqueue("queued either")
    dumped = service.dump()
    thread.goal = dumped.goal
    thread.goal_queue = list(dumped.queue)
    manager.store.save_thread(thread)

    forked = await manager.fork_thread(thread.id)
    assert forked.goal is None
    assert forked.goal_queue == []
    assert forked.goal_fork_notice is True

    source = manager.store.load_thread(thread.id)
    assert source.goal is not None
    assert source.goal["objective"] == "Do not copy this"
