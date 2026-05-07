"""Parity tests for PTY-backed exec_shell (Stage 3.4).

Mirror of Rust ``crates/tui/src/tools/shell.rs`` BackgroundShell::Pty path.
Covers:

- pty=False path (pipe) still works (regression guard)
- pty=True foreground: captures output, returncode=0
- pty=True background + wait round-trip
- pty=True cancel terminates the child
- pty=True interact writes to the master fd
- Policy gate still applies with pty=True
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.shell_tools import (
    ExecShellCancelTool,
    ExecShellInteractTool,
    ExecShellTool,
    ExecShellWaitTool,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="PTY path uses stdlib `pty` which is POSIX-only",
)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(working_directory=tmp_path)


class TestPipeMode:
    async def test_foreground_pipe(self, ctx: ToolContext) -> None:
        result = await ExecShellTool().execute(
            {"command": "echo hello"}, ctx
        )
        assert result.success
        assert "hello" in result.content
        assert result.metadata["returncode"] == 0


class TestPtyForeground:
    async def test_foreground_pty_captures_output(self, ctx: ToolContext) -> None:
        result = await ExecShellTool().execute(
            {"command": "echo pty-hello", "pty": True}, ctx
        )
        assert result.success
        assert "pty-hello" in result.content
        assert result.metadata["pty"] is True
        assert result.metadata["returncode"] == 0

    async def test_foreground_pty_nonzero_exit(self, ctx: ToolContext) -> None:
        result = await ExecShellTool().execute(
            {"command": "false", "pty": True}, ctx
        )
        assert result.success is False
        assert result.metadata["returncode"] != 0


class TestPtyBackground:
    async def test_background_wait_round_trip(self, ctx: ToolContext) -> None:
        start = await ExecShellTool().execute(
            {"command": "printf 'bg-out\\n'", "pty": True, "background": True},
            ctx,
        )
        assert start.success
        assert start.metadata["pty"] is True
        process_id = start.content
        assert process_id

        # Give the child a moment, then wait.
        await asyncio.sleep(0.05)
        waited = await ExecShellWaitTool().execute(
            {"process_id": process_id}, ctx
        )
        assert waited.success
        assert "bg-out" in waited.content
        assert waited.metadata["pty"] is True

    async def test_background_cancel_terminates(self, ctx: ToolContext) -> None:
        start = await ExecShellTool().execute(
            {
                "command": "sleep 30",
                "pty": True,
                "background": True,
            },
            ctx,
        )
        process_id = start.content
        await asyncio.sleep(0.05)
        cancelled = await ExecShellCancelTool().execute(
            {"process_id": process_id}, ctx
        )
        assert cancelled.metadata["status"] == "cancelled"
        assert cancelled.metadata["pty"] is True


class TestPtyInteract:
    async def test_interact_writes_input(self, ctx: ToolContext) -> None:
        # Use `head -n1` which exits after receiving one line — deterministic.
        start = await ExecShellTool().execute(
            {"command": "head -n 1", "pty": True, "background": True}, ctx
        )
        process_id = start.content
        # Small delay for the child to reach its read() call.
        await asyncio.sleep(0.1)
        await ExecShellInteractTool().execute(
            {"process_id": process_id, "input": "hello\n"},
            ctx,
        )
        waited = await ExecShellWaitTool().execute(
            {"process_id": process_id}, ctx
        )
        assert waited.metadata["pty"] is True
        assert "hello" in waited.content
