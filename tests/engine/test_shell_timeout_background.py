"""Foreground exec_shell timeout converts to a background process."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.shell import (
    ExecShellTool,
    cancel_background_process,
    list_background_processes,
    running_attached_count,
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


async def test_timeout_converted_process_is_attached_but_background_is_not(
    tmp_path: Path,
):
    """Only the timeout-converted job holds a turn open."""
    ctx = ToolContext(working_directory=tmp_path)
    timed_out = await ExecShellTool().execute(
        {"command": "sleep 0.4 && echo attached", "timeout_ms": 50}, ctx
    )
    assert running_attached_count(ctx) == 1

    detached = await ExecShellTool().execute(
        {"command": "sleep 0.4 && echo detached", "background": True}, ctx
    )
    # The explicit background job must not add to the blocking count.
    assert running_attached_count(ctx) == 1

    listing = {item["process_id"]: item for item in list_background_processes(ctx)}
    assert listing[timed_out.metadata["process_id"]]["detached"] is False
    assert listing[detached.content]["detached"] is True

    await wait_background_process(ctx, timed_out.metadata["process_id"])
    assert running_attached_count(ctx) == 0
    await cancel_background_process(ctx, detached.content)


async def test_turn_handoff_waits_for_attached_process(engine_ctx):
    """The turn-end gate blocks until a re-homed shell delivers its result."""
    engine, _handle = engine_ctx
    messages: list[object] = []

    result = await ExecShellTool().execute(
        {"command": "sleep 0.3 && echo handed-off", "timeout_ms": 50},
        engine.tool_context,
    )
    process_id = result.metadata["process_id"]
    assert running_attached_count(engine.tool_context) == 1

    injected = await engine._handle_shell_process_turn_handoff(messages)

    assert injected is True
    assert len(messages) == 1
    body = str(messages[0].content)
    assert "<system-reminder>" in body
    assert "Background shell process finished." in body
    assert process_id in body
    assert "handed-off" in body
    # Consumed, so idle delivery cannot inject the same payload twice.
    assert process_id in engine._consumed_process_completions


async def test_turn_handoff_ignores_detached_process(engine_ctx):
    """An explicit background=true job must never hold the turn open."""
    engine, _handle = engine_ctx
    messages: list[object] = []

    result = await ExecShellTool().execute(
        {"command": "sleep 5", "background": True}, engine.tool_context
    )
    assert running_attached_count(engine.tool_context) == 0

    injected = await engine._handle_shell_process_turn_handoff(messages)

    assert injected is False
    assert messages == []
    await cancel_background_process(engine.tool_context, result.content)


async def test_agent_wait_action_waits_on_process_ids(tmp_path: Path):
    """action='wait' covers background shells, with wait_mode=all."""
    from deepseek_tui.tools.subagent.tools import AgentTool

    ctx = ToolContext(working_directory=tmp_path)
    first = await ExecShellTool().execute(
        {"command": "sleep 0.15 && echo one", "background": True}, ctx
    )
    second = await ExecShellTool().execute(
        {"command": "sleep 0.3 && echo two", "background": True}, ctx
    )

    result = await AgentTool().execute(
        {
            "action": "wait",
            "process_ids": [first.content, second.content],
            "wait_mode": "all",
            "timeout_ms": 5000,
        },
        ctx,
    )

    assert result.success is True
    assert set(result.metadata["waited_ids"]) == {first.content, second.content}
    outputs = " ".join(str(p.get("output", "")) for p in result.metadata["processes"])
    assert "one" in outputs
    assert "two" in outputs


async def test_agent_wait_rejects_mixed_agent_and_process_ids(tmp_path: Path):
    from deepseek_tui.tools.registry import ToolError
    from deepseek_tui.tools.subagent.tools import AgentTool

    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="not both"):
        await AgentTool().execute(
            {
                "action": "wait",
                "process_ids": ["p1"],
                "agent_ids": ["a1"],
            },
            ctx,
        )


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
