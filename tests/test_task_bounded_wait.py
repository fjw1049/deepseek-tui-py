import asyncio

import pytest

from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.task import (
    NewTaskRequest,
    TaskExecutionResult,
    TaskManager,
    TaskManagerConfig,
)
from deepseek_tui.tools.task.tools import TaskOutputTool


@pytest.mark.asyncio
async def test_wait_cancel_and_timeout_do_not_cancel_real_task(tmp_path):
    release = asyncio.Event()
    started = asyncio.Event()

    async def execute(task, cancel):
        started.set()
        await release.wait()
        (tmp_path / "report.txt").write_text("finished independently")
        return TaskExecutionResult(summary="finished independently")

    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path), executor=execute
    )
    await manager.start()
    try:
        task = await manager.add_task(NewTaskRequest(prompt="write report"))
        await asyncio.wait_for(started.wait(), 2)
        context = ToolContext(working_directory=tmp_path, task_manager=manager)
        tool = TaskOutputTool()
        result = await tool.execute({"task_id": task.id, "block": True, "timeout_ms": 10}, context)
        assert result.metadata["timed_out"]
        waiter = asyncio.create_task(tool.execute({"task_id": task.id, "block": True}, context))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not (await manager.get_task(task.id)).status.is_terminal()
        context.active_task_id = task.id
        with pytest.raises(ToolError, match="own completion"):
            await tool.execute({"task_id": task.id, "block": True}, context)
        context.active_task_id = None
        release.set()
        result = await tool.execute(
            {"task_id": task.id, "block": True, "timeout_ms": 2000}, context
        )
        assert result.metadata["status"] == "completed"
        assert "finished independently" in result.content
        assert (tmp_path / "report.txt").read_text() == "finished independently"
    finally:
        release.set()
        await manager.shutdown()
