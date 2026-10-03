from pathlib import Path

import pytest

from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig


@pytest.mark.asyncio
async def test_active_filter_applies_before_limit_and_ids_include_old_tasks(tmp_path: Path) -> None:
    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path))
    oldest = await manager.add_task(NewTaskRequest(prompt="old running work"))
    for index in range(101):
        task = await manager.add_task(NewTaskRequest(prompt=f"new {index}"))
        await manager.cancel_task(task.id)
    active = await manager.list_tasks(limit=1, active_only=True)
    assert [task.id for task in active] == [oldest.id]
    selected = await manager.list_tasks(task_ids=[oldest.id])
    assert [task.id for task in selected] == [oldest.id]
