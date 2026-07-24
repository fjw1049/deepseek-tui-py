"""agent_result / agent_cancel as generic background-job tools (Claude TaskOutput/TaskStop parity).

A background shell process (exec_shell background=true → process_id) is
managed through the same tools as sub-agents: agent_result fetches output
(optionally blocking), agent_cancel terminates.
"""

from __future__ import annotations

import pytest

from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.shell import ExecShellTool
from deepseek_tui.tools.subagent.tools import AgentCancelTool, AgentResultTool


async def _spawn(ctx: ToolContext, command: str) -> str:
    result = await ExecShellTool().execute(
        {"command": command, "background": True}, ctx
    )
    assert result.success is True
    return result.content


async def test_agent_result_collects_background_shell_output(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 0.1 && echo hi")

    result = await AgentResultTool().execute(
        {"process_id": pid, "block": True, "timeout_ms": 5000}, ctx
    )

    assert result.success is True
    assert result.content == "hi"
    assert result.metadata["status"] == "completed"
    assert result.metadata["process_id"] == pid


async def test_agent_result_peek_reports_running(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 30")
    try:
        result = await AgentResultTool().execute({"process_id": pid}, ctx)
        assert result.success is True
        assert result.metadata["status"] == "running"
        assert "still running" in result.content
    finally:
        await AgentCancelTool().execute({"process_id": pid}, ctx)


async def test_agent_result_block_timeout_returns_running(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 30")
    try:
        result = await AgentResultTool().execute(
            {"process_id": pid, "block": True, "timeout_ms": 1000}, ctx
        )
        assert result.metadata["status"] == "running"
        # Process survives the timed-out wait and can still be collected.
        cancel = await AgentCancelTool().execute({"process_id": pid}, ctx)
        assert cancel.metadata["status"] == "cancelled"
    finally:
        if pid:  # already cancelled above; ignore unknown-id errors
            try:
                await AgentCancelTool().execute({"process_id": pid}, ctx)
            except ToolError:
                pass


async def test_agent_cancel_stops_background_shell(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "sleep 30")

    result = await AgentCancelTool().execute({"process_id": pid}, ctx)

    assert result.success is True
    assert result.content == "cancelled"
    assert result.metadata["status"] == "cancelled"
    # Cancelled process is drained from the store.
    with pytest.raises(ToolError, match="Unknown process_id"):
        await AgentResultTool().execute({"process_id": pid}, ctx)


async def test_agent_result_requires_an_id(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="agent_id or process_id is required"):
        await AgentResultTool().execute({}, ctx)


async def test_agent_cancel_requires_an_id(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="agent_id or process_id is required"):
        await AgentCancelTool().execute({}, ctx)


async def test_agent_result_block_collects_large_output_within_timeout(tmp_path) -> None:
    """Regression: a child that fills the OS pipe buffer must not deadlock the
    timed wait (bare process.wait() never observes the exit while the child
    is blocked on write; the collector task drains the pipes instead)."""
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "dd if=/dev/zero bs=1024 count=300 2>/dev/null | base64")

    result = await AgentResultTool().execute(
        {"process_id": pid, "block": True, "timeout_ms": 10000}, ctx
    )

    assert result.metadata["status"] == "completed"
    assert result.metadata["returncode"] == 0
    assert len(result.metadata["stdout"]) > 300_000


async def test_agent_result_timeout_then_recollect_preserves_output(tmp_path) -> None:
    """A timed-out wait leaves the collector running; the next blocking call
    reuses it and still returns the full output."""
    ctx = ToolContext(working_directory=tmp_path)
    pid = await _spawn(ctx, "echo part1; sleep 2; echo part2")

    first = await AgentResultTool().execute(
        {"process_id": pid, "block": True, "timeout_ms": 1000}, ctx
    )
    assert first.metadata["status"] == "running"

    second = await AgentResultTool().execute(
        {"process_id": pid, "block": True, "timeout_ms": 10000}, ctx
    )
    assert second.metadata["status"] == "completed"
    assert "part1" in second.content
    assert "part2" in second.content


async def test_agent_result_rejects_ambiguous_ids(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="either agent_id or process_id"):
        await AgentResultTool().execute({"agent_id": "a1", "process_id": "p1"}, ctx)


async def test_agent_cancel_rejects_ambiguous_ids(tmp_path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="either agent_id or process_id"):
        await AgentCancelTool().execute({"agent_id": "a1", "process_id": "p1"}, ctx)
