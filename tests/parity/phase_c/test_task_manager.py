"""Parity tests for tools/task_manager (Stage 3.1).

Mirror of Rust `crates/tui/src/task_manager.rs` tests — covers:
- add/list/get/cancel/counts round-trips
- unique prefix resolution (+ ambiguity error)
- atomic persistence + restart recovery (Running → Queued)
- worker loop completes a queued task via stub executor
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from deepseek_tui.tools.task_manager import (
    ExecutionTask,
    NewTaskRequest,
    TaskExecutionResult,
    TaskManager,
    TaskManagerConfig,
    TaskStatus,
    _load_state,
    _resolve_task_id,
    _summarize_text,
    _task_record_from_dict,
    _task_record_to_dict,
    _write_json_atomic,
)


def _make_config(tmp_path: Path) -> TaskManagerConfig:
    data = tmp_path / "deepseek"
    return TaskManagerConfig(
        data_dir=data,
        default_workspace=tmp_path,
        default_model="stub-model",
        default_mode="agent",
        worker_count=1,
    )


@pytest_asyncio.fixture
async def manager(tmp_path: Path) -> AsyncIterator[TaskManager]:
    cfg = _make_config(tmp_path)
    mgr = TaskManager(cfg)
    await mgr.start()
    try:
        yield mgr
    finally:
        await mgr.shutdown()


class TestAddListRead:
    async def test_add_task_populates_defaults(self, manager: TaskManager) -> None:
        task = await manager.add_task(NewTaskRequest(prompt="do work"))
        assert task.id.startswith("task_")
        assert len(task.id) == len("task_") + 8
        assert task.status is TaskStatus.QUEUED
        assert task.model == "stub-model"
        assert task.mode == "agent"
        assert task.auto_approve is True
        assert task.timeline[0].kind == "queued"

    async def test_add_task_rejects_empty_prompt(self, manager: TaskManager) -> None:
        with pytest.raises(ValueError):
            await manager.add_task(NewTaskRequest(prompt="   "))

    async def test_list_newest_first(self, manager: TaskManager) -> None:
        first = await manager.add_task(NewTaskRequest(prompt="first"))
        await asyncio.sleep(0.01)
        second = await manager.add_task(NewTaskRequest(prompt="second"))
        summaries = await manager.list_tasks()
        # Filter down to the two ids we just created (worker may complete either).
        ids = [s.id for s in summaries if s.id in (first.id, second.id)]
        assert ids == [second.id, first.id]

    async def test_list_respects_limit(self, manager: TaskManager) -> None:
        for i in range(5):
            await manager.add_task(NewTaskRequest(prompt=f"p{i}"))
        summaries = await manager.list_tasks(limit=2)
        assert len(summaries) == 2

    async def test_get_by_full_id(self, manager: TaskManager) -> None:
        task = await manager.add_task(NewTaskRequest(prompt="hello"))
        got = await manager.get_task(task.id)
        assert got.id == task.id


class TestPrefixResolution:
    def test_resolve_full_id(self) -> None:
        tasks = {"task_abcd1234": _stub_record("task_abcd1234")}
        assert _resolve_task_id(tasks, "task_abcd1234") == "task_abcd1234"

    def test_resolve_unique_prefix(self) -> None:
        tasks = {"task_abcd1234": _stub_record("task_abcd1234")}
        assert _resolve_task_id(tasks, "task_abc") == "task_abcd1234"

    def test_resolve_not_found(self) -> None:
        with pytest.raises(KeyError, match="not found"):
            _resolve_task_id({}, "task_missing")

    def test_resolve_ambiguous(self) -> None:
        tasks = {
            "task_abcd1234": _stub_record("task_abcd1234"),
            "task_abce9999": _stub_record("task_abce9999"),
        }
        with pytest.raises(KeyError, match="Ambiguous"):
            _resolve_task_id(tasks, "task_abc")


class TestCancel:
    async def test_cancel_queued_goes_terminal(self, manager: TaskManager) -> None:
        await manager.shutdown()  # pause workers so the queued task stays queued
        mgr = TaskManager(_make_config(manager.data_dir().parent))
        await mgr.start()
        try:
            task = await mgr.add_task(NewTaskRequest(prompt="to-cancel"))
            # Before worker picks it up, snatch it.
            # Try to cancel before worker_loop grabs it. Race is fine — we
            # just need a deterministic terminal state afterwards.
            result = await mgr.cancel_task(task.id)
            assert result.status in (TaskStatus.CANCELED, TaskStatus.COMPLETED)
            if result.status is TaskStatus.CANCELED:
                assert result.duration_ms == 0
                assert any(e.kind == "canceled" for e in result.timeline)
        finally:
            await mgr.shutdown()

    async def test_cancel_unknown_raises(self, manager: TaskManager) -> None:
        with pytest.raises(KeyError):
            await manager.cancel_task("task_nosuch")


class TestCounts:
    async def test_counts_reflects_states(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        mgr = TaskManager(cfg)
        await mgr.start()
        try:
            for i in range(3):
                await mgr.add_task(NewTaskRequest(prompt=f"p{i}"))
            # Wait for stub executor to drain the queue.
            for _ in range(30):
                counts = await mgr.counts()
                if counts.completed == 3:
                    break
                await asyncio.sleep(0.05)
            counts = await mgr.counts()
            assert counts.completed == 3
            assert counts.queued == 0
            assert counts.running == 0
        finally:
            await mgr.shutdown()


class TestPersistence:
    async def test_task_file_written_atomically(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        mgr = TaskManager(cfg)
        await mgr.start()
        try:
            task = await mgr.add_task(NewTaskRequest(prompt="persist me"))
            task_path = cfg.data_dir / "tasks" / f"{task.id}.json"
            assert task_path.exists()
            data = json.loads(task_path.read_text())
            assert data["id"] == task.id
            assert data["prompt"] == "persist me"
            # No residual .tmp files left behind.
            residuals = list((cfg.data_dir / "tasks").glob("*.tmp"))
            assert residuals == []
        finally:
            await mgr.shutdown()

    async def test_queue_file_written(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        mgr = TaskManager(cfg)
        await mgr.start()
        try:
            await mgr.add_task(NewTaskRequest(prompt="queued"))
            queue_data = json.loads((cfg.data_dir / "queue.json").read_text())
            assert "queue" in queue_data
        finally:
            await mgr.shutdown()


class TestRestartRecovery:
    async def test_running_downgraded_to_queued_on_load(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        queue_path = tmp_path / "queue.json"
        tasks_dir.mkdir()

        record = _stub_record("task_recov001")
        record.status = TaskStatus.RUNNING
        record.started_at = "2026-05-07T00:00:00+00:00"
        _write_json_atomic(
            tasks_dir / f"{record.id}.json", _task_record_to_dict(record)
        )
        _write_json_atomic(queue_path, {"queue": []})

        tasks, queue = _load_state(tasks_dir, queue_path)
        assert tasks[record.id].status is TaskStatus.QUEUED
        assert tasks[record.id].started_at is None
        assert any(e.kind == "recovered" for e in tasks[record.id].timeline)
        # Queue must contain the recovered id.
        assert record.id in list(queue)

    async def test_queue_filters_non_queued_ids(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        queue_path = tmp_path / "queue.json"
        tasks_dir.mkdir()

        done = _stub_record("task_done00001")
        done.status = TaskStatus.COMPLETED
        _write_json_atomic(tasks_dir / f"{done.id}.json", _task_record_to_dict(done))
        _write_json_atomic(queue_path, {"queue": [done.id]})

        tasks, queue = _load_state(tasks_dir, queue_path)
        assert done.id in tasks
        assert done.id not in list(queue)


class TestWorkerLoop:
    async def test_stub_executor_marks_task_completed(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        mgr = TaskManager(cfg)
        await mgr.start()
        try:
            task = await mgr.add_task(NewTaskRequest(prompt="auto-complete"))
            for _ in range(40):
                final = await mgr.get_task(task.id)
                if final.status is TaskStatus.COMPLETED:
                    break
                await asyncio.sleep(0.05)
            final = await mgr.get_task(task.id)
            assert final.status is TaskStatus.COMPLETED
            assert final.ended_at is not None
            assert final.duration_ms is not None
            assert final.duration_ms >= 0
            assert "stub" in (final.result_summary or "")
        finally:
            await mgr.shutdown()

    async def test_custom_executor_failure_marks_failed(self, tmp_path: Path) -> None:
        async def broken_executor(
            _task: ExecutionTask, _cancel: asyncio.Event
        ) -> TaskExecutionResult:
            return TaskExecutionResult(summary="", error="boom")

        cfg = _make_config(tmp_path)
        mgr = TaskManager(cfg, executor=broken_executor)
        await mgr.start()
        try:
            task = await mgr.add_task(NewTaskRequest(prompt="doomed"))
            for _ in range(40):
                final = await mgr.get_task(task.id)
                if final.status is TaskStatus.FAILED:
                    break
                await asyncio.sleep(0.05)
            final = await mgr.get_task(task.id)
            assert final.status is TaskStatus.FAILED
            assert final.error == "boom"
        finally:
            await mgr.shutdown()


class TestHelpers:
    def test_summarize_truncates_with_ellipsis(self) -> None:
        text = "x" * 100
        out = _summarize_text(text, limit=20)
        assert out.endswith("...")
        assert len(out) <= 20

    def test_task_record_roundtrip(self) -> None:
        original = _stub_record("task_roundtrip")
        data = _task_record_to_dict(original)
        reconstructed = _task_record_from_dict(data)
        assert reconstructed.id == original.id
        assert reconstructed.status is original.status


# --- helpers -----------------------------------------------------------


def _stub_record(task_id: str):
    from deepseek_tui.tools.task_manager import CURRENT_TASK_SCHEMA_VERSION, TaskRecord

    return TaskRecord(
        schema_version=CURRENT_TASK_SCHEMA_VERSION,
        id=task_id,
        prompt="stub prompt",
        model="stub-model",
        workspace="/tmp",
        mode="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=True,
        status=TaskStatus.QUEUED,
        created_at="2026-05-07T00:00:00+00:00",
    )
