"""Unit tests for edit_file no-match diagnostics and path suggestions."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.tools.utils.edit_diagnostics import (
    build_edit_no_match_message,
    looks_like_line_numbered_read_output,
    normalize_confusables,
    strip_line_number_prefixes,
)
from deepseek_tui.tools.file import EditFileTool, ReadFileTool
from deepseek_tui.tools.utils.path_suggestions import format_not_found_error
from deepseek_tui.tools.registry import ToolContext, ToolError


def test_strip_line_number_prefixes() -> None:
    raw = "12\thello\n13\tworld"
    assert strip_line_number_prefixes(raw) == "hello\nworld"
    assert looks_like_line_numbered_read_output(raw) is True
    assert looks_like_line_numbered_read_output("hello\nworld") is False


def test_confusable_normalization() -> None:
    assert normalize_confusables("\u201chello\u201d") == '"hello"'
    assert normalize_confusables("a\u2014b") == "a--b"


def test_no_match_detects_line_number_prefix() -> None:
    content = "hello\nworld\n"
    old = "1\thello\n2\tworld"
    msg = build_edit_no_match_message("x.py", old, content)
    assert "Search string not found" in msg
    assert "line-number" in msg.lower() or "LINE\\tCONTENT" in msg or "N\\t" in msg
    assert "hello" in strip_line_number_prefixes(old)


def test_no_match_confusable_hint() -> None:
    content = "say \u201chello\u201d\n"
    old = 'say "hello"'
    msg = build_edit_no_match_message("x.py", old, content)
    assert "typography" in msg.lower() or "smart quotes" in msg.lower()
    assert "read_file" in msg


def test_no_match_nearest_lines() -> None:
    content = "alpha\nbeta unique_token here\ngamma\n"
    msg = build_edit_no_match_message("x.py", "unique_token XX", content)
    assert "Search string not found" in msg
    assert "Nearest match" in msg
    assert "unique_token" in msg
    assert "read_file" in msg


@pytest.mark.asyncio
async def test_edit_file_line_prefix_error_is_actionable(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello\nworld\n", encoding="utf-8")
    ctx = ToolContext(working_directory=tmp_path)
    await ReadFileTool().execute({"path": "note.txt"}, ctx)

    with pytest.raises(ToolError, match="line.number|N\\\\tcontent") as excinfo:
        await EditFileTool().execute(
            {
                "path": "note.txt",
                "old_string": "1\thello\n2\tworld",
                "new_string": "hi\nthere",
            },
            ctx,
        )
    assert "Search string not found" in str(excinfo.value)


@pytest.mark.asyncio
async def test_edit_file_confusable_error(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("msg = \u201cok\u201d\n", encoding="utf-8")
    ctx = ToolContext(working_directory=tmp_path)
    await ReadFileTool().execute({"path": "note.txt"}, ctx)

    with pytest.raises(ToolError, match="typography|smart quotes") as excinfo:
        await EditFileTool().execute(
            {
                "path": "note.txt",
                "old_string": 'msg = "ok"',
                "new_string": 'msg = "yes"',
            },
            ctx,
        )
    assert "Search string not found" in str(excinfo.value)


@pytest.mark.asyncio
async def test_read_file_missing_path_suggests_similar(tmp_path: Path) -> None:
    (tmp_path / "utils.py").write_text("x = 1\n", encoding="utf-8")
    ctx = ToolContext(working_directory=tmp_path)

    with pytest.raises(ToolError, match="does not exist") as excinfo:
        await ReadFileTool().execute({"path": "util.py"}, ctx)
    msg = str(excinfo.value)
    assert "utils.py" in msg
    assert "working directory" in msg


@pytest.mark.asyncio
async def test_edit_file_missing_path_includes_cwd(tmp_path: Path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    with pytest.raises(ToolError, match="does not exist") as excinfo:
        await EditFileTool().execute(
            {
                "path": "missing.py",
                "old_string": "a",
                "new_string": "b",
            },
            ctx,
        )
    assert str(tmp_path) in str(excinfo.value)


def test_format_not_found_did_you_mean_under_cwd(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "foo.txt").write_text("hi\n", encoding="utf-8")
    # Asked for sibling under parent; real file lives under cwd/repo.
    asked = tmp_path / "foo.txt"
    msg = format_not_found_error(
        display_path="foo.txt",
        resolved_path=asked,
        cwd=repo,
    )
    assert "does not exist" in msg
    assert "Did you mean" in msg
    assert "foo.txt" in msg
