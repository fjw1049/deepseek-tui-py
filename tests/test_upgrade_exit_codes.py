"""Explicit success criteria follow real foreground and background processes."""

import shlex
import sys

import pytest

from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.shell import ExecShellTool
from deepseek_tui.tools.task.tools import TaskOutputTool


@pytest.mark.parametrize("pty", [False, True])
@pytest.mark.parametrize("kind", ["foreground", "background", "timeout"])
async def test_expected_exit_codes_follow_process(tmp_path, pty, kind):
    context = ToolContext(working_directory=tmp_path)
    script = "import time; time.sleep(.1); print('probe'); raise SystemExit(1)"
    result = await ExecShellTool().execute(
        {
            "command": f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}",
            "pty": pty,
            "background": kind == "background",
            "timeout_ms": 10 if kind == "timeout" else 5000,
            "expected_exit_codes": [0, 1],
        },
        context,
    )
    if kind != "foreground":
        result = await TaskOutputTool().execute(
            {"process_id": result.metadata["process_id"], "block": True}, context
        )
    assert result.success and result.metadata["returncode"] == 1
    assert result.metadata["expected_exit_codes"] == [0, 1]
    assert "[exit 1]" in result.content


@pytest.mark.parametrize("expected", [None, [0, 1]])
async def test_unexpected_exit_still_fails(tmp_path, expected):
    args = {"command": "exit 2"}
    if expected is not None:
        args["expected_exit_codes"] = expected
    result = await ExecShellTool().execute(args, ToolContext(working_directory=tmp_path))
    assert not result.success and result.metadata["returncode"] == 2


@pytest.mark.parametrize("expected", [[], [True], [-1], [256], "0"])
async def test_invalid_success_criteria_do_not_execute(tmp_path, expected):
    with pytest.raises((ToolError, ValueError)):
        await ExecShellTool().execute(
            {"command": "touch bad", "expected_exit_codes": expected},
            ToolContext(working_directory=tmp_path),
        )
    assert not (tmp_path / "bad").exists()
