from __future__ import annotations

import os

import pytest

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.file import ReadFileTool


@pytest.mark.asyncio
async def test_read_file_respects_offset_and_limit(tmp_path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = await ReadFileTool().execute(
        {"path": "sample.txt", "offset": 2, "limit": 2},
        ToolContext(working_directory=tmp_path),
    )

    assert result.success is True
    assert result.content == "two\nthree\n"
    assert result.metadata["line_offset"] == 2
    assert result.metadata["line_limit"] == 2
    assert result.metadata["total_lines"] == 4


@pytest.mark.asyncio
async def test_write_file_is_atomic_no_tmp_leftover(tmp_path) -> None:
    """M1: WriteFileTool writes atomically and leaves no .tmp files behind."""
    from deepseek_tui.tools.file import WriteFileTool

    target = tmp_path / "out.txt"
    result = await WriteFileTool().execute(
        {"path": "out.txt", "content": "hello\nworld\n"},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success is True
    assert target.read_text(encoding="utf-8") == "hello\nworld\n"
    assert not list(tmp_path.glob(".*.tmp"))


def test_write_text_atomic_failure_preserves_original(tmp_path, monkeypatch) -> None:
    """M1: if the final rename fails, the original is intact and the temp
    file is cleaned up - no half-written file on a crash-equivalent failure."""
    from deepseek_tui.utils import write_text_atomic

    target = tmp_path / "keep.txt"
    target.write_text("original", encoding="utf-8")

    real_replace = os.replace

    def _boom(src, dst):  # noqa: ANN001
        if str(dst).endswith("keep.txt"):
            raise OSError("rename disallowed")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError, match="rename disallowed"):
        write_text_atomic(target, "new-but-fails")

    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".*.tmp"))


def test_resolve_path_allows_extra_read_root_and_subdirs(tmp_path) -> None:
    """Read-only callers may reach files under a declared extra_read_root
    (and its nested subdirs) even though it lies outside the workspace."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin_root = tmp_path / "plugin"
    (plugin_root / "a" / "b").mkdir(parents=True)
    (plugin_root / "a" / "b" / "f.json").write_text("{}", encoding="utf-8")

    ctx = ToolContext(
        working_directory=workspace,
        extra_read_roots=(plugin_root.resolve(),),
    )

    top = ctx.resolve_path(str(plugin_root / "manifest.json"), allow_read_roots=True)
    assert top == (plugin_root / "manifest.json").resolve()
    nested = ctx.resolve_path(str(plugin_root / "a" / "b" / "f.json"), allow_read_roots=True)
    assert nested == (plugin_root / "a" / "b" / "f.json").resolve()


def test_resolve_path_write_still_confined_to_workspace(tmp_path) -> None:
    """A read root does NOT grant write access: without allow_read_roots the
    same outside path is still rejected."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()

    ctx = ToolContext(
        working_directory=workspace,
        extra_read_roots=(plugin_root.resolve(),),
    )

    with pytest.raises(ValueError, match="escapes workspace"):
        ctx.resolve_path(str(plugin_root / "out.txt"))


def test_resolve_path_default_context_unchanged(tmp_path) -> None:
    """Regression: with no extra_read_roots, behavior is exactly as before —
    inside-workspace ok, outside raises regardless of allow_read_roots."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "elsewhere" / "f.txt"

    ctx = ToolContext(working_directory=workspace)

    inside = ctx.resolve_path("note.txt")
    assert inside == (workspace / "note.txt").resolve()

    with pytest.raises(ValueError, match="escapes workspace"):
        ctx.resolve_path(str(outside), allow_read_roots=True)
