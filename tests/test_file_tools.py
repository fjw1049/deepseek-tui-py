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
async def test_read_file_rejects_oversize_unpageable_file(tmp_path) -> None:
    from deepseek_tui.tools.file import _MAX_READ_FILE_BYTES
    from deepseek_tui.tools.registry import ToolError

    target = tmp_path / "huge.bin"
    target.write_bytes(b"x" * (_MAX_READ_FILE_BYTES + 10))

    with pytest.raises(ToolError, match="byte read limit"):
        await ReadFileTool().execute(
            {"path": "huge.bin"}, ToolContext(working_directory=tmp_path)
        )


@pytest.mark.asyncio
async def test_read_file_pages_past_the_byte_budget(tmp_path) -> None:
    """The byte budget bounds what a page returns, not how far it may reach.

    ``bytes_scanned`` counted from byte 0 on every call, so once a file passed
    1 MiB every offset beyond that point aborted: the scan stopped before it
    reached the requested line and the tool reported the file unreadable. The
    skipped bytes are discarded, so they cost nothing and must not be charged
    against the page budget — otherwise the back half of any large file is
    unreachable through ``read_file`` at all.
    """
    from deepseek_tui.tools.file import _MAX_READ_FILE_BYTES

    target = tmp_path / "big.log"
    target.write_text(
        "".join(f"line {i:06d} " + "." * 20 + "\n" for i in range(1, 40_001)),
        encoding="utf-8",
    )
    assert target.stat().st_size > _MAX_READ_FILE_BYTES

    result = await ReadFileTool().execute(
        {"path": "big.log", "offset": 39_998, "limit": 3},
        ToolContext(working_directory=tmp_path),
    )

    assert result.success is True
    lines = [line for line in result.content.splitlines() if "\t" in line]
    assert lines[0].startswith("39998\tline 039998")
    assert lines[-1].startswith("40000\tline 040000")


@pytest.mark.asyncio
async def test_read_file_omits_total_lines_when_the_scan_stops_early(
    tmp_path, monkeypatch
) -> None:
    """A partial scan must not report 'scanned so far' as the file length."""
    import deepseek_tui.tools.file as file_tools

    monkeypatch.setattr(file_tools, "_MAX_READ_SCAN_BYTES", 4096)
    (tmp_path / "big.log").write_text(
        "".join(f"line {i:06d}\n" for i in range(1, 30_001)), encoding="utf-8"
    )

    result = await ReadFileTool().execute(
        {"path": "big.log", "offset": 1, "limit": 2},
        ToolContext(working_directory=tmp_path),
    )

    assert result.success is True
    assert "1\tline 000001" in result.content
    assert "total_lines" not in result.metadata
    assert "use offset to continue" in result.content
    assert " of " not in [
        line for line in result.content.splitlines() if "use offset to continue" in line
    ][0]


@pytest.mark.asyncio
async def test_read_file_points_forward_when_the_offset_is_unreachable(
    tmp_path, monkeypatch
) -> None:
    """The old message said "use a smaller offset" — the opposite of the fix."""
    import deepseek_tui.tools.file as file_tools
    from deepseek_tui.tools.registry import ToolError

    # The budget is checked once per 64 KiB chunk, so the file has to be worth
    # more than one chunk for the give-up path to be reachable at all.
    monkeypatch.setattr(file_tools, "_MAX_READ_SCAN_BYTES", 4096)
    target = tmp_path / "big.log"
    target.write_text(
        "".join(f"line {i:06d}\n" for i in range(1, 30_001)), encoding="utf-8"
    )

    with pytest.raises(ToolError) as excinfo:
        await ReadFileTool().execute(
            {"path": "big.log", "offset": 29_900},
            ToolContext(working_directory=tmp_path),
        )

    message = str(excinfo.value)
    assert "smaller offset" not in message
    assert "exec_shell" in message


@pytest.mark.asyncio
async def test_read_file_rejects_binary_nul(tmp_path) -> None:
    from deepseek_tui.tools.registry import ToolError

    (tmp_path / "pic.bin").write_bytes(b"hello\x00world\n")
    with pytest.raises(ToolError, match="not a UTF-8 text file"):
        await ReadFileTool().execute(
            {"path": "pic.bin"}, ToolContext(working_directory=tmp_path)
        )
