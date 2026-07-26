"""Spillover footer points at read_file/grep_files; resolve_path allows reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.tools import runtime
from deepseek_tui.tools.registry import ToolContext, ToolResult
from deepseek_tui.tools.runtime import (
    SPILLOVER_THRESHOLD_BYTES,
    apply_spillover,
    set_test_spillover_root,
)


@pytest.fixture
def spillover_dir(tmp_path, monkeypatch):
    root = tmp_path / "tool_outputs"
    monkeypatch.setattr(runtime, "_TEST_SPILLOVER_ROOT", root)
    yield root
    set_test_spillover_root(None)


def _big_result() -> ToolResult:
    content = "x" * (SPILLOVER_THRESHOLD_BYTES + 1024)
    return ToolResult(success=True, content=content)


def test_footer_points_to_read_file_and_grep_files(spillover_dir):
    result = apply_spillover(_big_result(), "call-1")
    assert result.success
    assert "read_file" in result.content
    assert "grep_files" in result.content
    assert "retrieve_tool_result" not in result.content
    spillover_path = Path(result.metadata["spillover_path"])
    assert spillover_path.is_file()
    assert str(spillover_path) in result.content
    # The full output actually landed on disk.
    assert len(spillover_path.read_text(encoding="utf-8")) > SPILLOVER_THRESHOLD_BYTES


def test_resolve_path_allows_spillover_reads_not_writes(spillover_dir, tmp_path):
    result = apply_spillover(_big_result(), "call-2")
    spillover_path = result.metadata["spillover_path"]

    context = ToolContext(working_directory=tmp_path / "ws")
    resolved = context.resolve_path(spillover_path, allow_read_roots=True)
    assert resolved == Path(spillover_path).resolve()

    with pytest.raises(ValueError, match="path escapes workspace"):
        context.resolve_path(spillover_path, allow_read_roots=False)


def test_resolve_path_spillover_root_none_not_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "_TEST_SPILLOVER_ROOT", None)
    monkeypatch.setattr(
        runtime, "spillover_root", lambda: None
    )
    context = ToolContext(working_directory=tmp_path / "ws")
    with pytest.raises(ValueError, match="path escapes workspace"):
        context.resolve_path(str(tmp_path / "elsewhere" / "x.txt"), allow_read_roots=True)
