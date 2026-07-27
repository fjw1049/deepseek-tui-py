"""task_output / task_stop as generic background-job tools (Claude TaskOutput/TaskStop parity).

A background shell process (exec_shell background=true → process_id) is
managed through the same tools as sub-agents and durable tasks:
task_output(process_id) fetches output (optionally blocking),
task_stop(process_id) terminates.
"""

from __future__ import annotations

import pytest

from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.shell import ExecShellTool
from deepseek_tui.tools.subagent.tools import AgentTool
from deepseek_tui.tools.task.tools import TaskOutputTool, TaskStopTool


async def _spawn(ctx: ToolContext, command: str) -> str:
    result = await ExecShellTool().execute(
        {"command": command, "background": True}, ctx
    )
    assert result.success is True
    return result.content


async def test_task_output_collects_background_shell_output(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 0.1 && echo hi")

    result = await TaskOutputTool().execute(
        {"process_id": pid, "block": True, "timeout_ms": 5000}, ctx
    )

    assert result.success is True
    assert result.content == "hi"
    assert result.metadata["status"] == "completed"
    assert result.metadata["process_id"] == pid


async def test_task_output_peek_reports_running(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 30")
    try:
        result = await TaskOutputTool().execute({"process_id": pid}, ctx)
        assert result.success is True
        assert result.metadata["status"] == "running"
        assert "still running" in result.content
    finally:
        await TaskStopTool().execute({"process_id": pid}, ctx)


async def test_task_output_block_timeout_returns_running(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 30")
    try:
        result = await TaskOutputTool().execute(
            {"process_id": pid, "block": True, "timeout_ms": 1000}, ctx
        )
        assert result.metadata["status"] == "running"
        # Process survives the timed-out wait and can still be collected.
        cancel = await TaskStopTool().execute({"process_id": pid}, ctx)
        assert cancel.metadata["status"] == "cancelled"
    finally:
        if pid:  # already cancelled above; ignore unknown-id errors
            try:
                await TaskStopTool().execute({"process_id": pid}, ctx)
            except ToolError:
                pass


async def test_task_stop_stops_background_shell(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 30")

    result = await TaskStopTool().execute({"process_id": pid}, ctx)

    assert result.success is True
    assert result.content == "cancelled"
    assert result.metadata["status"] == "cancelled"
    # Cancelled process is drained from the store.
    with pytest.raises(ToolError, match="Unknown process_id"):
        await TaskOutputTool().execute({"process_id": pid}, ctx)


async def test_task_output_requires_an_id(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="task_id', 'agent_id', or 'process_id"):
        await TaskOutputTool().execute({}, ctx)


async def test_task_stop_requires_an_id(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="task_id"):
        await TaskStopTool().execute({}, ctx)


async def test_task_output_block_collects_large_output_within_timeout(tmp_path) -> None:
    """Regression: a child that fills the OS pipe buffer must not deadlock the
    timed wait (bare process.wait() never observes the exit while the child
    is blocked on write; the collector task drains the pipes instead)."""
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "dd if=/dev/zero bs=1024 count=300 2>/dev/null | base64")

    result = await TaskOutputTool().execute(
        {"process_id": pid, "block": True, "timeout_ms": 10000}, ctx
    )

    assert result.metadata["status"] == "completed"
    assert result.metadata["returncode"] == 0
    assert len(result.metadata["stdout"]) > 300_000


async def test_task_output_timeout_then_recollect_preserves_output(tmp_path) -> None:
    """A timed-out wait leaves the collector running; the next blocking call
    reuses it and still returns the full output."""
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "echo part1; sleep 2; echo part2")

    first = await TaskOutputTool().execute(
        {"process_id": pid, "block": True, "timeout_ms": 1000}, ctx
    )
    assert first.metadata["status"] == "running"

    second = await TaskOutputTool().execute(
        {"process_id": pid, "block": True, "timeout_ms": 10000}, ctx
    )
    assert second.metadata["status"] == "completed"
    assert "part1" in second.content
    assert "part2" in second.content


async def test_task_output_rejects_ambiguous_ids(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="either agent_id or process_id"):
        await TaskOutputTool().execute(
            {"agent_id": "a1", "process_id": "p1"}, ctx
        )


async def test_task_stop_rejects_ambiguous_ids(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="either agent_id or process_id"):
        await TaskStopTool().execute(
            {"agent_id": "a1", "process_id": "p1"}, ctx
        )


# --- agent tool: retired actions steer to the task tools --------------------


async def test_agent_requires_an_action(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="action is required"):
        await AgentTool().execute({}, ctx)


async def test_agent_rejects_unknown_action(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="unknown agent action"):
        await AgentTool().execute({"action": "teleport"}, ctx)


async def test_agent_retired_actions_steer_to_task_tools(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    for action, target in (
        ("list", "task_list"),
        ("result", "task_output"),
        ("cancel", "task_stop"),
    ):
        with pytest.raises(ToolError, match=f"use {target} instead"):
            await AgentTool().execute({"action": action}, ctx)


# --- exec_shell process_id/input branch (retired exec_shell_interact) -------


async def test_exec_shell_interact_branch_writes_stdin(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "cat")

    sent = await ExecShellTool().execute(
        {"process_id": pid, "input": "hello\n", "close_stdin": True}, ctx
    )
    assert sent.success is True
    assert sent.metadata["process_id"] == pid

    from deepseek_tui.tools.shell import wait_background_process

    collected = await wait_background_process(ctx, pid)
    assert collected.metadata["status"] == "completed"
    assert collected.content == "hello"


async def test_exec_shell_interact_close_stdin_without_input(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "cat")

    sent = await ExecShellTool().execute(
        {"process_id": pid, "close_stdin": True}, ctx
    )
    assert sent.success is True

    from deepseek_tui.tools.shell import wait_background_process

    collected = await wait_background_process(ctx, pid)
    assert collected.metadata["status"] == "completed"


async def test_exec_shell_interact_requires_input_or_close(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 30")
    try:
        with pytest.raises(ToolError, match="requires 'input'"):
            await ExecShellTool().execute({"process_id": pid}, ctx)
    finally:
        await TaskStopTool().execute({"process_id": pid}, ctx)


async def test_exec_shell_process_id_mutually_exclusive_with_command(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="mutually exclusive"):
        await ExecShellTool().execute(
            {"command": "echo hi", "process_id": "p1"}, ctx
        )


async def test_exec_shell_requires_command_or_process_id(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="command must be a string"):
        await ExecShellTool().execute({}, ctx)
