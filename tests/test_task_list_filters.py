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
    await manager.shutdown()


async def test_id_poll_reads_only_selected_evicted_records(tmp_path, monkeypatch):
    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path))
    try:
        first = await manager.add_task(NewTaskRequest(prompt="first"))
        await manager.cancel_task(first.id)
        for index in range(60):
            record = await manager.add_task(NewTaskRequest(prompt=str(index)))
            await manager.cancel_task(record.id)
        async with manager._lock:
            manager._evict_terminal_tasks_locked()
        assert first.id not in manager._tasks
        manager._catalog_cache.clear()
        read_paths = []
        original = Path.read_text

        def read(path, *args, **kwargs):
            read_paths.append(path)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read)
        records = await manager.list_tasks(task_ids=[first.id, first.id, "../outside", "absent"])
        assert [r.id for r in records] == [first.id]
        assert [path.name for path in read_paths] == [f"{first.id}.json"]
        read_paths.clear()
        assert await manager.list_tasks(task_ids=[]) == []
        assert not read_paths
    finally:
        await manager.shutdown()


async def test_running_scheduler_active_poll_does_not_scan_history(tmp_path, monkeypatch):
    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path))
    await manager.start()
    try:
        record = await manager.add_task(NewTaskRequest(prompt="queued"))

        def no_history(*args, **kwargs):
            raise AssertionError("active polling must not scan completed history")

        monkeypatch.setattr(manager, "_catalog", no_history)
        assert [r.id for r in await manager.list_tasks(active_only=True)] == [record.id]
    finally:
        await manager.shutdown()
