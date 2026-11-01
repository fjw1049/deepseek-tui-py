"""An error's wording must describe what failed, not what its text happens to contain."""

from deepseek_tui.engine.dispatch import format_tool_error


def test_edit_failure_under_a_folder_named_workspace_is_not_a_path_escape():
    message = "Search string not found in /work/workspace/app.py"
    assert format_tool_error(ValueError(message), "edit_file") == message


def test_a_real_escape_still_says_so():
    text = format_tool_error(ValueError("path escapes workspace: ../x"), "read_file")
    assert text.startswith("Path escapes workspace")


def test_invalid_timeout_argument_is_not_a_timeout():
    message = "Tool browser_use invalid arguments: 900000 is greater than the maximum (timeout_ms)"
    assert "timed out" not in format_tool_error(ValueError(message), "browser_use")


def test_a_real_timeout_still_says_so():
    assert "timed out" in format_tool_error(TimeoutError("timeout after 30s"), "exec_shell")
