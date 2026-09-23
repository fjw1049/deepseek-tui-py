import pytest

from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig
from deepseek_tui.tools.task.store import _load_state


def test_corrupt_queue_file_recovers_empty_queue(tmp_path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    queue_path = tmp_path / "queue.json"
    queue_path.write_text("{broken", encoding="utf-8")

    tasks, queue = _load_state(tasks_dir, queue_path)

    assert tasks == {}
    assert list(queue) == []


@pytest.mark.asyncio
async def test_reloading_ignores_malformed_task_record(tmp_path) -> None:
    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path))
    manager._tasks_dir.mkdir(parents=True)
    (manager._tasks_dir / "task_broken.json").write_text(
        '{"status":"not_a_status"}', encoding="utf-8"
    )
    with pytest.raises(KeyError, match="not found"):
        await manager.get_task("task_broken")


@pytest.mark.asyncio
async def test_reloading_rejects_ambiguous_task_prefix(tmp_path) -> None:
    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path))
    await manager.add_task(NewTaskRequest(prompt="first"))
    await manager.add_task(NewTaskRequest(prompt="second"))
    manager._tasks.clear()
    with pytest.raises(KeyError, match="Ambiguous"):
        await manager.get_task("task_")
