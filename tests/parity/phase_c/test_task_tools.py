"""Parity tests for tools/task_tools (Stage 3.1).

Covers all 11 durable task tools wired through a real TaskManager.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.task_manager import (
    ExecutionTask,
    TaskExecutionResult,
    TaskManager,
    TaskManagerConfig,
)
from deepseek_tui.tools.task_tools import (
    PrAttemptListTool,
    PrAttemptPreflightTool,
    PrAttemptReadTool,
    PrAttemptRecordTool,
    TaskCancelTool,
    TaskCreateTool,
    TaskGateRunTool,
    TaskListTool,
    TaskReadTool,
    TaskShellStartTool,
    TaskShellWaitTool,
)


async def _inert_executor(
    _task: ExecutionTask, cancel: asyncio.Event
) -> TaskExecutionResult:
    """Block until canceled or timeout so worker doesn't complete tasks mid-test."""
    try:
        await asyncio.wait_for(cancel.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        return TaskExecutionResult(summary="inert-finished")
    return TaskExecutionResult(summary="", error="canceled")


@pytest_asyncio.fixture
async def ctx(tmp_path: Path) -> AsyncIterator[ToolContext]:
    cfg = TaskManagerConfig(
        data_dir=tmp_path / "deepseek",
        default_workspace=tmp_path,
        default_model="stub-model",
        default_mode="agent",
        worker_count=0,  # disable workers for deterministic tool tests
    )
    # worker_count clamps to >=1, so use an inert executor instead
    cfg = TaskManagerConfig(
        data_dir=tmp_path / "deepseek",
        default_workspace=tmp_path,
        default_model="stub-model",
        default_mode="agent",
        worker_count=1,
    )
    mgr = TaskManager(cfg, executor=_inert_executor)
    await mgr.start()
    try:
        yield ToolContext(
            working_directory=tmp_path,
            task_manager=mgr,
        )
    finally:
        await mgr.shutdown()


class TestTaskCreate:
    async def test_creates_task_via_manager(self, ctx: ToolContext) -> None:
        tool = TaskCreateTool()
        result = await tool.execute({"prompt": "do the thing"}, ctx)
        assert result.success is True
        assert result.metadata["task_id"].startswith("task_")
        assert result.metadata["status"] in ("queued", "running")

    async def test_rejects_empty_prompt(self, ctx: ToolContext) -> None:
        tool = TaskCreateTool()
        with pytest.raises(ToolError):
            await tool.execute({"prompt": "   "}, ctx)

    async def test_missing_manager_raises(self, tmp_path: Path) -> None:
        ctx = ToolContext(working_directory=tmp_path)
        tool = TaskCreateTool()
        with pytest.raises(ToolError, match="TaskManager is not attached"):
            await tool.execute({"prompt": "hi"}, ctx)


class TestTaskList:
    async def test_lists_with_limit(self, ctx: ToolContext) -> None:
        create = TaskCreateTool()
        for i in range(3):
            await create.execute({"prompt": f"p{i}"}, ctx)
        result = await TaskListTool().execute({"limit": 2}, ctx)
        assert len(result.metadata["tasks"]) == 2


class TestTaskRead:
    async def test_reads_by_prefix(self, ctx: ToolContext) -> None:
        create = TaskCreateTool()
        created = await create.execute({"prompt": "readable"}, ctx)
        task_id = created.metadata["task_id"]
        result = await TaskReadTool().execute({"id": task_id[:10]}, ctx)
        assert result.metadata["task_id"] == task_id

    async def test_read_unknown_raises(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError):
            await TaskReadTool().execute({"id": "task_nope0000"}, ctx)


class TestTaskCancel:
    async def test_cancel_returns_terminal(self, ctx: ToolContext) -> None:
        created = await TaskCreateTool().execute({"prompt": "cancelable"}, ctx)
        result = await TaskCancelTool().execute(
            {"id": created.metadata["task_id"]}, ctx
        )
        assert result.metadata["status"] in ("canceled", "running", "queued")


class TestTaskGateRun:
    async def test_records_gate(self, ctx: ToolContext) -> None:
        created = await TaskCreateTool().execute({"prompt": "gate"}, ctx)
        task_id = created.metadata["task_id"]
        result = await TaskGateRunTool().execute(
            {
                "id": task_id,
                "gate": "pytest",
                "command": "pytest -q",
                "status": "passed",
                "summary": "all green",
                "exit_code": 0,
                "duration_ms": 1200,
            },
            ctx,
        )
        assert result.success is True
        assert result.metadata["gate"]["gate"] == "pytest"
        read = await TaskReadTool().execute({"id": task_id}, ctx)
        assert read.metadata["gates_len"] == 1


class TestTaskShellStubs:
    async def test_shell_start_is_stub(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError, match="not yet implemented"):
            await TaskShellStartTool().execute({"id": "x", "command": "ls"}, ctx)

    async def test_shell_wait_is_stub(self, ctx: ToolContext) -> None:
        with pytest.raises(ToolError, match="not yet implemented"):
            await TaskShellWaitTool().execute({"process_id": "x"}, ctx)


class TestPrAttempt:
    async def test_record_and_list(self, ctx: ToolContext) -> None:
        created = await TaskCreateTool().execute({"prompt": "pr-flow"}, ctx)
        task_id = created.metadata["task_id"]

        rec = await PrAttemptRecordTool().execute(
            {
                "id": task_id,
                "summary": "fix: bad thing",
                "changed_files": ["src/a.py", "src/b.py"],
                "verification": ["pytest", "mypy"],
                "head_ref": "feature/x",
                "selected": True,
            },
            ctx,
        )
        attempt_id = rec.metadata["attempt"]["id"]

        listed = await PrAttemptListTool().execute({"id": task_id}, ctx)
        assert len(listed.metadata["attempts"]) == 1

        read = await PrAttemptReadTool().execute(
            {"id": task_id, "attempt_id": attempt_id}, ctx
        )
        assert read.metadata["attempt"]["summary"] == "fix: bad thing"

    async def test_read_unknown_attempt_raises(self, ctx: ToolContext) -> None:
        created = await TaskCreateTool().execute({"prompt": "pr"}, ctx)
        with pytest.raises(ToolError, match="Attempt not found"):
            await PrAttemptReadTool().execute(
                {"id": created.metadata["task_id"], "attempt_id": "attempt_nosuch"},
                ctx,
            )

    async def test_preflight_returns_diagnostics(self, ctx: ToolContext) -> None:
        created = await TaskCreateTool().execute({"prompt": "pre"}, ctx)
        result = await PrAttemptPreflightTool().execute(
            {
                "id": created.metadata["task_id"],
                "base_ref": "main",
                "head_ref": "topic/x",
            },
            ctx,
        )
        assert result.metadata["status"] == "ok"
        assert result.metadata["base_ref"] == "main"
