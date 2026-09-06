import asyncio
import os
import shlex
import sys

import pytest

from deepseek_tui.server.approval import ApprovalBridge, HttpApprovalHandler
from deepseek_tui.tools.approval import ApprovalRequest, RiskLevel, ToolCategory
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.shell import ExecShellTool
from deepseek_tui.tools.task import (
    NewTaskRequest,
    TaskExecutionResult,
    TaskManager,
    TaskManagerConfig,
    TaskStatus,
)


async def test_stop_waits_for_cleanup_before_reporting_canceled(tmp_path):
    started, cleaning, allow_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def executor(task, cancel):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await allow_cleanup.wait()

    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path), executor=executor
    )
    await manager.start()
    try:
        record = await manager.add_task(NewTaskRequest(prompt="blocked"))
        await asyncio.wait_for(started.wait(), 1)
        stopper = asyncio.create_task(manager.cancel_task(record.id))
        try:
            await asyncio.wait_for(cleaning.wait(), 1)
            assert record.status is TaskStatus.RUNNING
            assert not stopper.done()
            allow_cleanup.set()
            result = await asyncio.wait_for(stopper, 1)
            assert result.status is TaskStatus.CANCELED
        finally:
            allow_cleanup.set()
            stopper.cancel()
            await asyncio.gather(stopper, return_exceptions=True)
    finally:
        allow_cleanup.set()
        await manager.shutdown()


async def test_stop_interrupts_approval_and_worker_remains_available(tmp_path):
    bridge = ApprovalBridge()
    waiting = asyncio.Event()

    async def executor(task, cancel):
        if task.prompt == "next":
            return TaskExecutionResult(summary="done")
        waiting.set()
        await HttpApprovalHandler(bridge).request_approval(
            "call",
            ApprovalRequest(
                tool_name="exec_shell",
                risk_level=RiskLevel.MEDIUM,
                category=ToolCategory.CODE_EXEC,
                reason="wait",
            ),
        )
        return TaskExecutionResult(summary="should not run")

    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path), executor=executor
    )
    await manager.start()
    try:
        record = await manager.add_task(NewTaskRequest(prompt="approval"))
        await asyncio.wait_for(waiting.wait(), 1)
        await asyncio.wait_for(manager.cancel_task(record.id), 1)
        assert record.status is TaskStatus.CANCELED
        assert bridge.list_pending() == []
        next_record = await manager.add_task(NewTaskRequest(prompt="next"))
        async with asyncio.timeout(2):
            while not next_record.status.is_terminal():  # noqa: ASYNC110 -- observe durable status
                await asyncio.sleep(0.01)
        assert next_record.status is TaskStatus.COMPLETED
    finally:
        await manager.shutdown()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
async def test_stop_kills_real_shell_descendant_before_return(tmp_path):
    marker = tmp_path / "pid"
    code = (
        "import os,time,pathlib; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(60)"
    )
    script = tmp_path / "sleeper.py"
    script.write_text(code)
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"

    async def executor(task, cancel):
        result = await ExecShellTool().execute(
            {"command": command, "timeout_ms": 600000}, ToolContext(working_directory=tmp_path)
        )
        return TaskExecutionResult(summary=result.content)

    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path), executor=executor
    )
    await manager.start()
    try:
        record = await manager.add_task(NewTaskRequest(prompt="sleep"))
        async with asyncio.timeout(3):
            while not marker.exists():  # noqa: ASYNC110 -- observe child process startup
                await asyncio.sleep(0.01)
        pid = int(marker.read_text())
        await asyncio.wait_for(manager.cancel_task(record.id), 3)
        assert record.status is TaskStatus.CANCELED
        async with asyncio.timeout(2):
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.01)
    finally:
        await manager.shutdown()


async def test_stop_during_engine_initialization_closes_resources(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.dispatch import real_task_executor

    started = asyncio.Event()
    client = SimpleNamespace(close=AsyncMock())
    runtime = SimpleNamespace(context=SimpleNamespace(trust_mode=False), shutdown=AsyncMock())
    monkeypatch.setattr("deepseek_tui.config.loader.ConfigLoader.load", lambda self: Config())
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda cfg: client)
    monkeypatch.setattr(
        "deepseek_tui.tools.runtime.create_tool_runtime", AsyncMock(return_value=runtime)
    )

    async def create_engine(**kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("deepseek_tui.engine.orchestrator.Engine.create", create_engine)
    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path),
        executor=real_task_executor,
    )
    await manager.start()
    try:
        task = await manager.add_task(NewTaskRequest(prompt="start"))
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(manager.cancel_task(task.id), 1)
        assert task.status is TaskStatus.CANCELED
        runtime.shutdown.assert_awaited_once()
        client.close.assert_awaited_once()
    finally:
        await manager.shutdown()
