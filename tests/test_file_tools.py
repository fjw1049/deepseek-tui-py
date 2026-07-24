from __future__ import annotations

import json
import os

import pytest

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.file import ListDirTool, ReadFileTool


@pytest.mark.asyncio
async def test_read_file_respects_offset_and_limit(tmp_path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = await ReadFileTool().execute(
        {"path": "sample.txt", "offset": 2, "limit": 2},
        ToolContext(working_directory=tmp_path),
    )

    assert result.success is True
    assert result.content == (
        "2\ttwo\n3\tthree\n"
        "... (showing lines 2-3 of 4; use offset to continue)"
    )
    assert result.metadata["line_offset"] == 2
    assert result.metadata["line_limit"] == 2
    assert result.metadata["total_lines"] == 4


@pytest.mark.asyncio
async def test_read_file_adds_line_numbers_from_offset(tmp_path) -> None:
    """cat -n style numbering starts at the requested offset."""
    target = tmp_path / "sample.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = await ReadFileTool().execute(
        {"path": "sample.txt", "offset": 2},
        ToolContext(working_directory=tmp_path),
    )

    assert result.content == "2\ttwo\n3\tthree"


@pytest.mark.asyncio
async def test_read_file_default_limit_truncates_with_note(tmp_path) -> None:
    target = tmp_path / "big.txt"
    target.write_text(
        "\n".join(f"line {i}" for i in range(1, 2101)) + "\n", encoding="utf-8"
    )

    result = await ReadFileTool().execute(
        {"path": "big.txt"}, ToolContext(working_directory=tmp_path)
    )

    lines = result.content.splitlines()
    assert len(lines) == 2001  # 2000 numbered lines + truncation note
    assert lines[0] == "1\tline 1"
    assert lines[1999] == "2000\tline 2000"
    assert lines[2000] == (
        "... (showing lines 1-2000 of 2100; use offset to continue)"
    )
    assert result.metadata["total_lines"] == 2100


@pytest.mark.asyncio
async def test_read_file_explicit_limit_reports_showing_range(tmp_path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = await ReadFileTool().execute(
        {"path": "sample.txt", "offset": 2, "limit": 3},
        ToolContext(working_directory=tmp_path),
    )

    # offset 2 + limit 3 covers lines 2-4 == whole tail: nothing elided, no note.
    assert "use offset to continue" not in result.content

    partial = await ReadFileTool().execute(
        {"path": "sample.txt", "offset": 1, "limit": 2},
        ToolContext(working_directory=tmp_path),
    )
    assert partial.content.splitlines()[-1] == (
        "... (showing lines 1-2 of 4; use offset to continue)"
    )


@pytest.mark.asyncio
async def test_read_file_truncates_long_lines(tmp_path) -> None:
    target = tmp_path / "long.txt"
    target.write_text("ab\n" + "x" * 3000 + "\n", encoding="utf-8")

    result = await ReadFileTool().execute(
        {"path": "long.txt"}, ToolContext(working_directory=tmp_path)
    )

    lines = result.content.splitlines()
    assert lines[0] == "1\tab"
    assert lines[1].startswith("2\t" + "x" * 100)
    assert lines[1].endswith("... (line truncated)")
    assert len(lines[1]) == 2 + 2000 + len("... (line truncated)")


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


@pytest.mark.asyncio
async def test_write_file_reports_line_start_one(tmp_path) -> None:
    """write_file replaces/creates the whole file: mutation starts at line 1."""
    from deepseek_tui.tools.file import WriteFileTool

    result = await WriteFileTool().execute(
        {"path": "out.txt", "content": "hello\n"},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success is True
    assert result.metadata["mutation"]["line_start"] == 1


@pytest.mark.asyncio
async def test_edit_file_reports_first_occurrence_line(tmp_path) -> None:
    """edit_file mutation line_start is the 1-based line of the first match."""
    from deepseek_tui.tools.file import EditFileTool

    target = tmp_path / "note.txt"
    target.write_text("one\ntwo\nmark\nfour\nmark\n", encoding="utf-8")

    result = await EditFileTool().execute(
        {"path": "note.txt", "old_string": "mark", "new_string": "MARK",
         "replace_all": True},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success is True
    assert result.metadata["mutation"]["line_start"] == 3
    assert result.metadata["occurrences"] == 2


@pytest.mark.asyncio
async def test_edit_file_rejects_non_unique_old_string(tmp_path) -> None:
    """Multiple matches without replace_all are an error naming the count."""
    from deepseek_tui.tools.file import EditFileTool
    from deepseek_tui.tools.registry import ToolError

    target = tmp_path / "note.txt"
    target.write_text("mark\nmark\n", encoding="utf-8")

    with pytest.raises(ToolError, match="occurs 2 times") as excinfo:
        await EditFileTool().execute(
            {"path": "note.txt", "old_string": "mark", "new_string": "MARK"},
            ToolContext(working_directory=tmp_path),
        )
    assert "replace_all=true" in str(excinfo.value)
    # File untouched on failure.
    assert target.read_text(encoding="utf-8") == "mark\nmark\n"


@pytest.mark.asyncio
async def test_edit_file_replace_all_replaces_every_occurrence(tmp_path) -> None:
    from deepseek_tui.tools.file import EditFileTool

    target = tmp_path / "note.txt"
    target.write_text("a\nmark\nb\nmark\nc\n", encoding="utf-8")

    result = await EditFileTool().execute(
        {"path": "note.txt", "old_string": "mark", "new_string": "MARK",
         "replace_all": True},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success is True
    assert target.read_text(encoding="utf-8") == "a\nMARK\nb\nMARK\nc\n"
    assert result.metadata["occurrences"] == 2


@pytest.mark.asyncio
async def test_edit_file_legacy_search_replace_aliases(tmp_path) -> None:
    """Legacy ``search``/``replace`` keys still map to old_string/new_string."""
    from deepseek_tui.tools.file import EditFileTool

    target = tmp_path / "note.txt"
    target.write_text("hello world\n", encoding="utf-8")

    result = await EditFileTool().execute(
        {"path": "note.txt", "search": "world", "replace": "there"},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success is True
    assert target.read_text(encoding="utf-8") == "hello there\n"


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
    """Regression: with no extra_read_roots, behavior is exactly as before -
    inside-workspace ok, outside raises regardless of allow_read_roots."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "elsewhere" / "f.txt"

    ctx = ToolContext(working_directory=workspace)

    inside = ctx.resolve_path("note.txt")
    assert inside == (workspace / "note.txt").resolve()

    with pytest.raises(ValueError, match="escapes workspace"):
        ctx.resolve_path(str(outside), allow_read_roots=True)


@pytest.mark.asyncio
async def test_list_dir_honors_extra_read_roots(tmp_path) -> None:
    """list_dir is READ_ONLY and must honor extra_read_roots (e.g. a mounted
    plugin's own dir), like read_file/grep_files. Regression: list_dir used to
    call resolve_path without allow_read_roots=True, so listing a mounted
    plugin's directory was rejected as 'path escapes workspace' even though
    read_file on the same dir worked - forcing the model to fall back to
    exec_shell."""

    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin_root = tmp_path / "plugin" / "demo"
    (plugin_root / "skills").mkdir(parents=True)
    (plugin_root / "skills" / "SKILL.md").write_text("x", encoding="utf-8")
    (plugin_root / "plugin.json").write_text("{}", encoding="utf-8")

    ctx = ToolContext(working_directory=workspace, extra_read_roots=(plugin_root.resolve(),))

    # Listing the plugin dir (outside workspace) now succeeds via the grant.
    result = await ListDirTool().execute({"path": str(plugin_root)}, ctx)
    assert result.success
    names = {e["name"] for e in json.loads(result.content)}
    assert "plugin.json" in names and "skills" in names

    # Without the grant (default context), list_dir on the plugin dir is
    # still rejected - the grant is opt-in per context, not global.
    bare_ctx = ToolContext(working_directory=workspace)
    with pytest.raises(Exception, match="escapes workspace"):
        await ListDirTool().execute({"path": str(plugin_root)}, bare_ctx)
