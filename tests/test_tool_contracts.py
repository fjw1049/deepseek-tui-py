"""Facts the harness guarantees, so the model need not check them itself."""

from pathlib import Path

import pytest

from deepseek_tui.engine.context import load_project_context_with_parents
from deepseek_tui.engine.tools import missing_tool_error_message
from deepseek_tui.tools.file import EditFileTool, WriteFileTool
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.shell import (
    FOREGROUND_SLEEP_REFUSAL,
    ExecShellTool,
    _is_foreground_sleep,
)


@pytest.mark.parametrize("command", [
    "sleep 5", "sleep 30", "  sleep 30  ", "sleep 1m", "sleep 0.5h", "sleep 10 && curl localhost",
    "sleep 10; cat out.log",
])
def test_waiting_by_holding_the_turn_is_refused(command):
    assert _is_foreground_sleep(command)


@pytest.mark.parametrize("command", [
    "sleep 1", "sleep 2 && curl localhost", "until curl -s x; do sleep 5; done",
    "for i in 1 2; do sleep 10; done", "pytest; sleep 5", "echo sleep 30", "sleepwalk 30",
])
def test_a_short_settle_or_a_polling_loop_is_not(command):
    assert not _is_foreground_sleep(command)


async def test_refused_sleep_names_the_way_to_wait(tmp_path):
    result = await ExecShellTool().execute(
        {"command": "sleep 30"}, ToolContext(working_directory=tmp_path))
    assert not result.success
    assert result.content == FOREGROUND_SLEEP_REFUSAL
    assert "task_output" in result.content and "until" in result.content


async def test_background_sleep_stays_allowed(tmp_path):
    result = await ExecShellTool().execute(
        {"command": "sleep 30", "background": True}, ToolContext(working_directory=tmp_path))
    assert result.success, result.content


@pytest.mark.parametrize("foreign,real", [
    ("exec_command", "exec_shell"), ("Bash", "exec_shell"), ("apply_patch", "edit_file"),
    ("str_replace", "edit_file"), ("Read", "read_file"), ("glob", "file_search"),
])
def test_names_from_other_agents_map_to_the_real_tool(foreign, real):
    catalog = [{"function": {"name": real}}]
    assert f"Use {real} instead" in missing_tool_error_message(foreign, catalog)


def test_an_equivalent_outside_the_catalog_is_not_offered():
    message = missing_tool_error_message("exec_command", [{"function": {"name": "read_file"}}])
    assert "exec_shell" not in message


@pytest.mark.parametrize("tool", [WriteFileTool(), EditFileTool()])
def test_write_tools_promise_success_means_written(tool):
    assert "do not read it back" in tool.description()


def _instructions(path: Path, text: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "AGENTS.md").write_text(text)


def test_instructions_above_a_repository_do_not_apply(tmp_path):
    _instructions(tmp_path, "OUTSIDE")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    work = repo / "pkg"
    work.mkdir()
    ctx = load_project_context_with_parents(work, home_dir=tmp_path / "home")
    assert ctx.instructions is None or "OUTSIDE" not in ctx.instructions
    ctx = load_project_context_with_parents(repo, home_dir=tmp_path / "home")
    assert ctx.instructions is None or "OUTSIDE" not in ctx.instructions


def test_a_repository_root_still_serves_its_subdirectories(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _instructions(repo, "REPO")
    work = repo / "pkg"
    work.mkdir()
    assert "REPO" in load_project_context_with_parents(work, home_dir=tmp_path / "h").instructions


def test_instructions_in_home_are_not_project_instructions(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _instructions(home, "HOME")
    work = home / "Desktop" / "task"
    work.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    ctx = load_project_context_with_parents(work, home_dir=tmp_path / "other")
    assert ctx.instructions is None or "HOME" not in ctx.instructions


def test_injected_instructions_say_they_are_loaded(tmp_path):
    _instructions(tmp_path / "w", "RULES")
    block = load_project_context_with_parents(tmp_path / "w", home_dir=tmp_path / "h").as_system_block()
    assert "do not read these files again" in block and "RULES" in block
