"""Unit tests for turn-local same-args tool-call dedup."""

from __future__ import annotations

import asyncio

import pytest

from deepseek_tui.engine.tool_dedup import (
    REPEAT_FORCE_STOP_STREAK,
    REPEAT_REMINDER_1_START,
    ToolCallDeduplicator,
    make_tool_call_key,
)


def test_canonical_key_is_order_independent() -> None:
    a = make_tool_call_key("grep_files", {"path": "a", "pattern": "x"})
    b = make_tool_call_key("grep_files", {"pattern": "x", "path": "a"})
    assert a == b


def test_same_batch_reuse() -> None:
    dedup = ToolCallDeduplicator()
    dedup.begin_batch()
    first = dedup.classify("read_file", {"path": "a.py"})
    assert first.kind == "execute"
    dedup.record(first.key, "file body", is_error=False)

    second = dedup.classify("read_file", {"path": "a.py"})
    assert second.kind == "reuse"
    assert second.reuse_content == "file body"
    reused = dedup.reuse_content(second)
    assert "Duplicate tool call" in reused
    assert "file body" in reused


def test_cross_round_reminder_and_block() -> None:
    dedup = ToolCallDeduplicator()
    args = {"path": "a.py"}

    for _ in range(REPEAT_REMINDER_1_START - 1):
        dedup.begin_batch()
        d = dedup.classify("read_file", args)
        assert d.kind == "execute"
        content = dedup.decorate_execute_content(d, "ok")
        assert "<system-reminder>" not in content
        dedup.record(d.key, "ok", is_error=False)
        dedup.end_batch()

    dedup.begin_batch()
    d = dedup.classify("read_file", args)
    assert d.kind == "execute"
    assert d.projected_streak == REPEAT_REMINDER_1_START
    content = dedup.decorate_execute_content(d, "ok")
    assert "repeated several times" in content
    dedup.record(d.key, "ok", is_error=False)
    dedup.end_batch()

    # Drive streak up to the force-stop threshold.
    while True:
        dedup.begin_batch()
        d = dedup.classify("read_file", args)
        if d.kind == "block":
            assert d.projected_streak >= REPEAT_FORCE_STOP_STREAK
            assert "was not executed again" in dedup.block_content(d)
            break
        dedup.record(d.key, "ok", is_error=False)
        dedup.end_batch()
        assert d.projected_streak < REPEAT_FORCE_STOP_STREAK + 2


def test_different_args_reset_streak() -> None:
    dedup = ToolCallDeduplicator()
    for _ in range(4):
        dedup.begin_batch()
        d = dedup.classify("read_file", {"path": "a.py"})
        dedup.record(d.key, "a", is_error=False)
        dedup.end_batch()

    dedup.begin_batch()
    d = dedup.classify("read_file", {"path": "b.py"})
    assert d.kind == "execute"
    assert d.projected_streak == 1
    assert "<system-reminder>" not in dedup.decorate_execute_content(d, "b")


def test_reset_turn_clears_streak() -> None:
    dedup = ToolCallDeduplicator()
    for _ in range(5):
        dedup.begin_batch()
        d = dedup.classify("grep_files", {"pattern": "x"})
        dedup.record(d.key, "hits", is_error=False)
        dedup.end_batch()

    dedup.reset_turn()
    d = dedup.classify("grep_files", {"pattern": "x"})
    assert d.projected_streak == 1


def test_dynamic_progress_can_continue_beyond_identical_call_limit() -> None:
    dedup = ToolCallDeduplicator()
    for progress in range(20):
        dedup.begin_batch()
        decision = dedup.classify("task_output", {"agent_id": "example", "block": True})
        assert decision.kind == "execute"
        content = f"Processed {progress} files"
        dedup.record(decision.key, content, is_error=False)
        assert dedup.decorate_execute_content(decision, content) == content
        dedup.end_batch()


def test_dynamic_poll_without_progress_still_stops() -> None:
    dedup = ToolCallDeduplicator()
    for _ in range(REPEAT_FORCE_STOP_STREAK - 1):
        dedup.begin_batch()
        decision = dedup.classify("agent", {"action": "wait", "agent_ids": ["example"]})
        assert decision.kind == "execute"
        dedup.record(decision.key, "still running", is_error=False)
        dedup.end_batch()
    dedup.begin_batch()
    assert dedup.classify("agent", {"action": "wait", "agent_ids": ["example"]}).kind == "block"


def test_new_spill_paths_do_not_count_as_task_progress():
    dedup = ToolCallDeduplicator()
    for attempt in range(REPEAT_FORCE_STOP_STREAK - 1):
        dedup.begin_batch()
        decision = dedup.classify("task_output", {"task_id": "task_example"})
        assert decision.kind == "execute"
        dedup.record(decision.key, f"Full result: /tmp/result-{attempt}.txt", is_error=False,
                     observation_content="same task result" * 10000)
        dedup.end_batch()
    dedup.begin_batch()
    assert dedup.classify("task_output", {"task_id": "task_example"}).kind == "block"


@pytest.mark.asyncio
async def test_real_background_task_progress_survives_twenty_polls(tmp_path):
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.task import TaskManager, TaskManagerConfig, NewTaskRequest, TaskExecutionResult
    from deepseek_tui.tools.task.tools import TaskOutputTool

    ready = asyncio.Queue()
    acknowledged = asyncio.Queue()

    async def executor(task, cancel):
        for index in range(20):
            (tmp_path / f"result-{index}.txt").write_text(f"Processed item {index}")
            await manager.record_tool_timeline(task.id, "progress", f"Wrote result-{index}.txt")
            await ready.put(index)
            await acknowledged.get()
        return TaskExecutionResult(summary="Wrote 20 result files")

    manager = TaskManager(TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path), executor=executor)
    await manager.start()
    try:
        task = await manager.add_task(NewTaskRequest(prompt="Create 20 result files"))
        context = ToolContext(working_directory=tmp_path, task_manager=manager)
        dedup = ToolCallDeduplicator()
        for index in range(20):
            assert await asyncio.wait_for(ready.get(), timeout=2) == index
            dedup.begin_batch()
            decision = dedup.classify("task_output", {"task_id": task.id})
            assert decision.kind == "execute"
            result = await TaskOutputTool().execute({"task_id": task.id, "timeout_ms": 5}, context)
            assert f"result-{index}.txt" in result.content
            dedup.record(decision.key, result.content, is_error=not result.success)
            assert dedup.decorate_execute_content(decision, result.content) == result.content
            dedup.end_batch()
            await acknowledged.put(index)
        assert len(list(tmp_path.glob("result-*.txt"))) == 20
        async def wait_completed():
            while not (await manager.get_task(task.id)).status.is_terminal():
                await asyncio.sleep(0.001)

        await asyncio.wait_for(wait_completed(), timeout=2)
        final = await TaskOutputTool().execute({"task_id": task.id, "timeout_ms": 5}, context)
        assert final.success and "Wrote 20 result files" in final.content
    finally:
        await manager.shutdown()


def test_bounded_runtime_wait_does_not_trip_busy_poll_guard():
    dedup = ToolCallDeduplicator()
    for _ in range(20):
        dedup.begin_batch()
        decision = dedup.classify("task_output", {"task_id": "waiting"})
        assert decision.kind == "execute"
        dedup.record(decision.key, "running", is_error=False, runtime_waited=True)
        assert dedup.decorate_execute_content(decision, "running") == "running"
        dedup.end_batch()
