"""Regressions for automation execution, scheduling and resumed delivery."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.state.secrets import SecretsManager
from deepseek_tui.tools.automation import (
    AutomationManager,
    AutomationRunStatus,
    CreateAutomationRequest,
)
from deepseek_tui.tools.runtime import _safe_task_executor
from deepseek_tui.tools.task import (
    ExecutionTask,
    TaskExecutionResult,
    TaskManager,
    TaskManagerConfig,
    TaskRecord,
    TaskStatus,
)


async def _settled(manager: TaskManager, task_id: str) -> TaskRecord:
    async def poll() -> TaskRecord:
        while True:
            task = await manager.get_task(task_id)
            if task.status.is_terminal():
                return task
            await asyncio.sleep(0.001)

    return await asyncio.wait_for(poll(), timeout=2)


async def test_missing_credentials_fail_task_and_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(SecretsManager, "resolve_api_key", lambda *_: None)
    cfg = Config()
    tasks = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path, config=cfg),
        executor=_safe_task_executor(cfg),
    )
    mgr = AutomationManager.open(tmp_path / "automations")
    automation = mgr.create_automation(
        CreateAutomationRequest(
            name="report",
            prompt="Generate a report",
            schedule="0 9 * * *",
            timezone="UTC",
        )
    )
    await tasks.start()
    try:
        run = await mgr.run_now(automation.id, tasks)
        assert run.task_id is not None
        task = await _settled(tasks, run.task_id)
        await mgr.reconcile_run_statuses(tasks)
        saved = mgr.list_runs(automation.id)[0]
        assert task.status is TaskStatus.FAILED
        assert saved.status is AutomationRunStatus.FAILED
        assert "missing_api_key" in (saved.error or "")
        assert task.result_summary is None
    finally:
        await tasks.shutdown()


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError("inbox unavailable")])
async def test_digest_failure_does_not_block_other_due_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    mgr = AutomationManager.open(tmp_path / "automations")
    now = datetime.now(timezone.utc)
    good, bad = [
        mgr.create_automation(
            CreateAutomationRequest(
                name=name,
                prompt="Generate report",
                schedule="0 9 * * *",
                timezone="UTC",
                digest={"sources": ["email:today_local"]} if name == "bad" else None,
            )
        )
        for name in ("good", "bad")
    ]
    for index, automation in enumerate((good, bad)):
        automation.next_run_at = (now - timedelta(seconds=1)).isoformat()
        automation.updated_at = (now + timedelta(seconds=index)).isoformat()
        mgr.save_automation(automation)

    async def digest(config: object) -> str:
        if config is not None:
            raise error
        return ""

    monkeypatch.setattr("deepseek_tui.automation.pipeline.build_digest_block", digest)
    tasks = SimpleNamespace(
        add_task=AsyncMock(
            return_value=SimpleNamespace(
                id="task-good",
                started_at=None,
                thread_id=None,
                turn_id=None,
            )
        )
    )
    for _ in range(2):
        await mgr.scheduler_tick(tasks)  # type: ignore[arg-type]
    failed = mgr.list_runs(bad.id)[0]
    assert failed.status is AutomationRunStatus.FAILED
    assert failed.task_id is None
    assert failed.ended_at is not None
    assert (str(error) or type(error).__name__) in (failed.error or "")
    assert mgr.list_runs(good.id)[0].task_id == "task-good"
    tasks.add_task.assert_awaited_once()


async def test_manual_run_records_digest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = AutomationManager.open(tmp_path / "automations")
    automation = mgr.create_automation(
        CreateAutomationRequest(
            name="report",
            prompt="report",
            schedule="0 9 * * *",
            timezone="UTC",
        )
    )
    build_prompt = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr("deepseek_tui.automation.pipeline.build_final_prompt", build_prompt)
    tasks = SimpleNamespace(add_task=AsyncMock())
    run = await mgr.run_now(automation.id, tasks)  # type: ignore[arg-type]
    assert mgr.list_runs(automation.id)[0].status is AutomationRunStatus.FAILED
    assert "TimeoutError" in (run.error or "")
    tasks.add_task.assert_not_awaited()


@pytest.mark.parametrize(
    ("first_status", "observe_resume", "delivery_fails", "resume_fails"),
    [
        (TaskStatus.FAILED, True, False, False),
        (TaskStatus.FAILED, False, False, False),
        (TaskStatus.FAILED, False, True, False),
        (TaskStatus.TIMED_OUT, False, False, False),
        (TaskStatus.CANCELED, False, False, False),
        (TaskStatus.FAILED, False, False, True),
    ],
)
async def test_resumed_task_updates_run_and_delivers_new_outcome_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_status: TaskStatus,
    observe_resume: bool,
    delivery_fails: bool,
    resume_fails: bool,
) -> None:
    attempts = 0
    finish_resume = asyncio.Event()

    async def executor(task: ExecutionTask, cancel: asyncio.Event) -> TaskExecutionResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if first_status is TaskStatus.CANCELED:
                cancel.set()
            return TaskExecutionResult(
                summary="",
                error="first attempt failed",
                timed_out=first_status is TaskStatus.TIMED_OUT,
            )
        await finish_resume.wait()
        return TaskExecutionResult(
            summary="recovered report",
            error="second attempt failed" if resume_fails else None,
        )

    tasks = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path),
        executor=executor,
    )
    mgr = AutomationManager.open(tmp_path / "automations")
    automation = mgr.create_automation(
        CreateAutomationRequest(
            name="report",
            prompt="report",
            schedule="0 9 * * *",
            timezone="UTC",
            delivery={"mode": "feishu", "to": "synthetic", "best_effort": False},
        )
    )
    deliver = AsyncMock(side_effect=RuntimeError("channel unavailable") if delivery_fails else None)
    monkeypatch.setattr("deepseek_tui.automation.pipeline._FeishuSink.deliver", deliver)
    await tasks.start()
    try:
        run = await mgr.run_now(automation.id, tasks)
        assert run.task_id is not None
        assert (await _settled(tasks, run.task_id)).status is first_status
        await mgr.reconcile_run_statuses(tasks)
        if delivery_fails:
            for _ in range(4):
                await mgr.reconcile_run_statuses(tasks)
            assert mgr.list_runs(automation.id)[0].delivery_attempts == 5
        else:
            before = deliver.await_count
            await mgr.reconcile_run_statuses(tasks)
            assert deliver.await_count == before

        before = deliver.await_count
        deliver.side_effect = None
        await tasks.resume_task(run.task_id)
        if observe_resume:
            await mgr.reconcile_run_statuses(tasks)
            pending = mgr.list_runs(automation.id)[0]
            assert pending.status in (AutomationRunStatus.QUEUED, AutomationRunStatus.RUNNING)
            assert pending.error is None and pending.ended_at is None
            assert not pending.delivery_done and pending.delivery_attempts == 0
        finish_resume.set()
        task = await _settled(tasks, run.task_id)
        for _ in range(3):
            await mgr.reconcile_run_statuses(tasks)
        saved = mgr.list_runs(automation.id)[0]
        assert saved.status is (
            AutomationRunStatus.FAILED if resume_fails else AutomationRunStatus.COMPLETED
        )
        assert saved.error == ("second attempt failed" if resume_fails else None)
        assert saved.ended_at == task.ended_at
        assert saved.delivery_done and saved.delivery_attempts == 0
        assert deliver.await_count == before + 1
        if not resume_fails:
            assert "recovered report" in deliver.await_args.kwargs["summary"]
    finally:
        await tasks.shutdown()
