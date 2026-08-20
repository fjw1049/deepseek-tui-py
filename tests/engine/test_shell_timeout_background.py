"""Foreground exec_shell timeout converts to a background process."""

from __future__ import annotations

import asyncio

from pathlib import Path

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.shell import (
    ExecShellTool,
    cancel_background_process,
    list_background_processes,
    wait_background_process,
)


async def test_foreground_timeout_keeps_process_and_is_collectable(tmp_path: Path):
    ctx = ToolContext(working_directory=tmp_path)
    result = await ExecShellTool().execute(
        {"command": "sleep 0.25 && echo done", "timeout_ms": 50},
        ctx,
    )

    assert result.success is True
    assert result.metadata["timed_out"] is True
    assert result.metadata["background"] is True
    process_id = result.metadata["process_id"]
    assert process_id in result.content
    assert any(item["process_id"] == process_id for item in list_background_processes(ctx))

    collected = await wait_background_process(ctx, process_id)
    assert collected.success is True
    assert "done" in collected.content


async def test_foreground_timeout_notifies_when_process_finishes(tmp_path: Path):
    finished = asyncio.Event()
    seen: dict[str, object] = {}

    def sink(payload: dict[str, object]) -> None:
        seen.update(payload)
        finished.set()

    ctx = ToolContext(working_directory=tmp_path, on_shell_process_done=sink)
    result = await ExecShellTool().execute(
        {"command": "sleep 0.2 && echo hello-bg", "timeout_ms": 50},
        ctx,
    )
    process_id = result.metadata["process_id"]

    await asyncio.wait_for(finished.wait(), timeout=3)
    assert seen["process_id"] == process_id
    assert seen["returncode"] == 0
    assert "hello-bg" in str(seen["output"])


async def test_explicit_background_also_notifies_when_done(tmp_path: Path):
    finished = asyncio.Event()
    seen: dict[str, object] = {}

    def sink(payload: dict[str, object]) -> None:
        seen.update(payload)
        finished.set()

    ctx = ToolContext(working_directory=tmp_path, on_shell_process_done=sink)
    result = await ExecShellTool().execute(
        {"command": "echo explicit", "background": True},
        ctx,
    )
    process_id = result.content

    await asyncio.wait_for(finished.wait(), timeout=3)
    assert seen["process_id"] == process_id
    assert "explicit" in str(seen["output"])


async def test_hard_cancel_still_kills_foreground_process(tmp_path: Path):
    ctx = ToolContext(working_directory=tmp_path)
    task = asyncio.create_task(
        ExecShellTool().execute(
            {"command": "sleep 30", "timeout_ms": 60_000},
            ctx,
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert list_background_processes(ctx) == []


async def test_task_output_after_timeout_does_not_require_rerun(tmp_path: Path):
    ctx = ToolContext(working_directory=tmp_path)
    result = await ExecShellTool().execute(
        {"command": "sleep 0.2 && echo collected", "timeout_ms": 50},
        ctx,
    )
    process_id = result.metadata["process_id"]
    try:
        from deepseek_tui.tools.task.tools import TaskOutputTool

        collected = await TaskOutputTool().execute(
            {"process_id": process_id, "block": True, "timeout_ms": 5000},
            ctx,
        )
        assert collected.metadata["status"] == "completed"
        assert "collected" in collected.content
    finally:
        try:
            await cancel_background_process(ctx, process_id)
        except Exception:
            pass


async def test_engine_wires_process_done_sink_and_idle_delivery(engine_ctx):
    from deepseek_tui.engine.handle import (
        PROCESS_BACKGROUND_DONE_KIND,
        SendMessageOp,
    )

    engine, handle = engine_ctx
    sink = engine.tool_context.on_shell_process_done
    assert sink is not None
    assert sink.__self__ is engine
    assert handle.is_turn_active() is False

    result = await ExecShellTool().execute(
        {"command": "echo engine-notify", "background": True},
        engine.tool_context,
    )
    process_id = result.content

    op = await asyncio.wait_for(handle.next_op(), timeout=3)
    assert isinstance(op, SendMessageOp)
    assert op.hidden is True
    assert op.internal_kind == PROCESS_BACKGROUND_DONE_KIND
    assert "Background shell process finished." in op.content
    assert process_id in op.content
    assert "engine-notify" in op.content
    assert "<system-reminder>" in op.content


async def test_engine_skips_idle_delivery_after_task_output(engine_ctx):
    engine, handle = engine_ctx
    engine._mark_process_tool_result_consumed(
        "task_output",
        {"process_id": "p1", "status": "completed"},
        {"process_id": "p1"},
    )
    engine._enqueue_shell_process_completion(
        {
            "process_id": "p1",
            "command": "echo x",
            "returncode": 0,
            "output": "x",
        }
    )
    assert engine._drain_process_completions() == []
    await asyncio.sleep(0.15)
    assert handle._op_queue.empty()
