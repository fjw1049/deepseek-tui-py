"""task_read / task_list must expose results in ToolResult.content.

The orchestrator only injects ``content`` into the model transcript;
metadata is for the UI. Status-only stubs left follow-up turns unable
to present completed background-task results.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.task.helpers import _task_result, _task_result_content
from deepseek_tui.tools.task.manager import TaskManager
from deepseek_tui.tools.task.models import (
    NewTaskRequest,
    TaskExecutionResult,
    TaskManagerConfig,
    TaskRecord,
    TaskStatus,
    TaskTimelineEntry,
)
from deepseek_tui.tools.task.tools import TaskListTool, TaskReadTool


def _completed_record(**overrides: object) -> TaskRecord:
    base = dict(
        schema_version=2,
        id="task_4bccc869",
        prompt="count .py files",
        model="deepseek-v4-pro",
        workspace="/tmp",
        mode="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=False,
        status=TaskStatus.COMPLETED,
        created_at="2026-07-17T06:18:00Z",
        started_at="2026-07-17T06:18:10Z",
        ended_at="2026-07-17T06:18:22Z",
        duration_ms=10355,
        result_summary="无法统计 robotgo：路径在工作区外且 shell 未批准",
        error=None,
        timeline=[],
    )
    base.update(overrides)
    return TaskRecord(**base)  # type: ignore[arg-type]


def test_task_result_content_includes_result_summary() -> None:
    task = _completed_record()
    content = _task_result_content("task_read", task)
    assert "task_read: task_4bccc869 [completed]" in content
    assert "无法统计 robotgo" in content
    assert "duration_ms: 10355" in content


def test_task_result_content_falls_back_to_timeline_tail() -> None:
    task = _completed_record(
        result_summary=None,
        timeline=[
            TaskTimelineEntry(
                timestamp="2026-07-17T06:18:12Z",
                kind="tool",
                summary="exec_shell denied",
            ),
            TaskTimelineEntry(
                timestamp="2026-07-17T06:18:20Z",
                kind="text",
                summary="Background executors cannot request user input",
            ),
        ],
    )
    content = _task_result_content("task_read", task)
    assert "timeline_tail:" in content
    assert "exec_shell denied" in content
    assert "cannot request user input" in content


def test_task_result_toolresult_content_reaches_model_context() -> None:
    task = _completed_record()
    result = _task_result("task_read", task)
    injected = compact_tool_result_for_context("deepseek-v4-pro", "task_read", result)
    assert "无法统计 robotgo" in injected
    # Must not collapse to the old status-only stub (~36 bytes).
    assert len(injected) > 36


@pytest.mark.asyncio
async def test_task_read_and_list_tools_expose_result_in_content(
    tmp_path: Path,
) -> None:
    async def executor(task, cancel):  # noqa: ANN001
        return TaskExecutionResult(summary="repo has 91 .py files")

    cfg = TaskManagerConfig(data_dir=tmp_path, default_workspace=tmp_path)
    manager = TaskManager(cfg, executor=executor)
    await manager.start()
    created = await manager.add_task(NewTaskRequest(prompt="count py files"))
    for _ in range(50):
        current = await manager.get_task(created.id)
        if current.status.is_terminal():
            break
        import asyncio

        await asyncio.sleep(0.05)
    else:
        await manager.shutdown()
        raise AssertionError("task did not complete")

    context = ToolContext(working_directory=tmp_path, task_manager=manager)
    read_result = await TaskReadTool().execute({"task_id": created.id}, context)
    assert "repo has 91 .py files" in read_result.content
    assert created.id in read_result.content

    list_result = await TaskListTool().execute({}, context)
    assert created.id in list_result.content
    assert "repo has 91 .py files" in list_result.content
    assert list_result.content != "1 task(s)"

    await manager.shutdown()
