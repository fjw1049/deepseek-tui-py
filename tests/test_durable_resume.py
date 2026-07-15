"""Tests for durable transcript store + Task/SubAgent resume semantics."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deepseek_tui.tools.durable_transcript import (
    DurableTranscript,
    clear_transcript,
    dicts_to_messages,
    load_transcript,
    save_transcript,
    subagent_transcript_path,
    task_transcript_path,
)
from deepseek_tui.tools.task.manager import TaskManager, _stub_executor
from deepseek_tui.tools.task.models import (
    NewTaskRequest,
    TaskExecutionResult,
    TaskManagerConfig,
    TaskStatus,
)


def test_transcript_roundtrip(tmp_path: Path) -> None:
    path = subagent_transcript_path(tmp_path, "agent_abc")
    save_transcript(
        path,
        DurableTranscript(
            owner_kind="subagent",
            owner_id="agent_abc",
            messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
            steps_taken=2,
            force_summary=True,
            checkpoint_reason="round",
        ),
    )
    loaded = load_transcript(path)
    assert loaded is not None
    assert loaded.owner_id == "agent_abc"
    assert loaded.steps_taken == 2
    assert loaded.force_summary is True
    assert len(loaded.messages) == 1
    clear_transcript(path)
    assert load_transcript(path) is None


def test_dicts_to_messages_warns_on_invalid_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dropping an unparsable message must be logged, not silent (could desync

    tool_use/tool_result pairing in the rest of the hydrated history).
    """
    raw = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "not-a-real-role", "content": "not-a-list"},
    ]
    with caplog.at_level("WARNING", logger="deepseek_tui.tools.durable_transcript"):
        messages = dicts_to_messages(raw)
    assert len(messages) == 1
    assert any("dropping invalid transcript message" in r.message for r in caplog.records)


def test_task_status_timed_out_is_terminal_and_resumable() -> None:
    assert TaskStatus.TIMED_OUT.is_terminal()
    assert TaskStatus.TIMED_OUT.is_resumable()
    assert not TaskStatus.COMPLETED.is_resumable()
    assert not TaskStatus.QUEUED.is_resumable()


@pytest.mark.asyncio
async def test_task_finalize_timeout_not_cancel(tmp_path: Path) -> None:
    async def timeout_executor(task, cancel):
        cancel.set()
        return TaskExecutionResult(
            summary="",
            error="Task timed out after 1s",
            timed_out=True,
        )

    mgr = TaskManager(
        TaskManagerConfig(
            data_dir=tmp_path / "tasks",
            default_workspace=tmp_path,
            worker_count=1,
        ),
        executor=timeout_executor,
    )
    await mgr.start()
    try:
        task = await mgr.add_task(NewTaskRequest(prompt="do something long"))
        for _ in range(50):
            current = await mgr.get_task(task.id)
            if current.status.is_terminal():
                break
            await asyncio.sleep(0.05)
        current = await mgr.get_task(task.id)
        assert current.status is TaskStatus.TIMED_OUT
        assert current.error and "timed out" in current.error.lower()
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_task_resume_requeues(tmp_path: Path) -> None:
    mgr = TaskManager(
        TaskManagerConfig(
            data_dir=tmp_path / "tasks",
            default_workspace=tmp_path,
            worker_count=1,
        ),
        executor=_stub_executor,
    )
    # Don't start workers — mutate queue directly.
    mgr._tasks_dir.mkdir(parents=True, exist_ok=True)
    task = await mgr.add_task(NewTaskRequest(prompt="resume me"))
    async with mgr._lock:
        record = mgr._tasks[task.id]
        record.status = TaskStatus.CANCELED
        record.error = "cancelled"
        mgr._queue.clear()
        mgr._persist_all_locked()

    resumed = await mgr.resume_task(task.id)
    assert resumed.status is TaskStatus.QUEUED
    assert resumed.error is None
    assert task.id in list(mgr._queue)


@pytest.mark.asyncio
async def test_task_resume_rejects_completed(tmp_path: Path) -> None:
    mgr = TaskManager(
        TaskManagerConfig(
            data_dir=tmp_path / "tasks",
            default_workspace=tmp_path,
            worker_count=1,
        ),
        executor=_stub_executor,
    )
    mgr._tasks_dir.mkdir(parents=True, exist_ok=True)
    task = await mgr.add_task(NewTaskRequest(prompt="done"))
    async with mgr._lock:
        record = mgr._tasks[task.id]
        record.status = TaskStatus.COMPLETED
        mgr._queue.clear()
        mgr._persist_all_locked()

    with pytest.raises(RuntimeError, match="cannot be resumed"):
        await mgr.resume_task(task.id)


def test_task_transcript_path(tmp_path: Path) -> None:
    path = task_transcript_path(tmp_path, "task_deadbeef")
    assert path.name == "task_deadbeef.json"
    assert "transcripts" in str(path)
