"""Parity tests for apply_patch (Stage 3.3).

Mirror of Rust ``crates/tui/src/tools/apply_patch.rs`` tests (1,469 lines).
Covers:

- parse_range / parse_unified_diff / parse_unified_diff_files
- apply_hunk exact + fuzzy (neighborhood search)
- cumulative offset across multi-hunk patches
- whitespace-normalized matching (rstrip)
- delete/create via ``/dev/null`` headers
- changes (full-file replacement) path
- ApplyPatchTool end-to-end via ToolContext
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.patch_engine import (
    ApplyPatchError,
    Hunk,
    HunkLine,
    HunkLineKind,
    _parse_range,
    apply_hunks_to_lines,
    matches_at_position,
    parse_unified_diff,
    parse_unified_diff_files,
)
from deepseek_tui.tools.utility_tools import ApplyPatchTool


class TestParseRange:
    def test_range_with_count(self) -> None:
        assert _parse_range("10,5") == (10, 5)

    def test_range_without_count_defaults_to_one(self) -> None:
        assert _parse_range("10") == (10, 1)

    def test_zero_count(self) -> None:
        assert _parse_range("1,0") == (1, 0)

    def test_invalid_raises(self) -> None:
        with pytest.raises(ApplyPatchError):
            _parse_range("abc")


class TestParseUnifiedDiff:
    def test_single_hunk(self) -> None:
        patch = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+modified line2\n"
            " line3\n"
        )
        hunks = parse_unified_diff(patch)
        assert len(hunks) == 1
        h = hunks[0]
        assert (h.old_start, h.old_count, h.new_start, h.new_count) == (1, 3, 1, 3)
        kinds = [line.kind for line in h.lines]
        assert kinds == [
            HunkLineKind.CONTEXT,
            HunkLineKind.REMOVE,
            HunkLineKind.ADD,
            HunkLineKind.CONTEXT,
        ]

    def test_multi_file(self) -> None:
        patch = (
            "--- a/foo.txt\n"
            "+++ b/foo.txt\n"
            "@@ -1 +1 @@\n"
            "-old foo\n"
            "+new foo\n"
            "--- a/bar.txt\n"
            "+++ b/bar.txt\n"
            "@@ -1 +1 @@\n"
            "-old bar\n"
            "+new bar\n"
        )
        files = parse_unified_diff_files(patch)
        assert [f.path for f in files] == ["foo.txt", "bar.txt"]

    def test_dev_null_creates(self) -> None:
        patch = (
            "--- /dev/null\n"
            "+++ b/new.txt\n"
            "@@ -0,0 +1,2 @@\n"
            "+line1\n"
            "+line2\n"
        )
        files = parse_unified_diff_files(patch)
        assert len(files) == 1
        assert files[0].path == "new.txt"
        assert files[0].create_if_missing is True
        assert files[0].delete_after is False

    def test_dev_null_deletes(self) -> None:
        patch = (
            "--- a/old.txt\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-line1\n"
            "-line2\n"
        )
        files = parse_unified_diff_files(patch)
        assert files[0].delete_after is True

    def test_invalid_header_raises(self) -> None:
        patch = "@@ bogus @@\n line1\n"
        with pytest.raises(ApplyPatchError):
            parse_unified_diff(patch)


class TestMatchesAtPosition:
    def test_exact_match(self) -> None:
        assert matches_at_position(["a", "b", "c"], ["a", "b"], 0) is True

    def test_offset_match(self) -> None:
        assert matches_at_position(["a", "b", "c"], ["b", "c"], 1) is True

    def test_whitespace_normalized(self) -> None:
        assert matches_at_position(["line  ", "x"], ["line"], 0) is True

    def test_no_match(self) -> None:
        assert matches_at_position(["a", "b"], ["x"], 0) is False

    def test_overflow(self) -> None:
        assert matches_at_position(["a"], ["a", "b"], 0) is False


class TestApplyHunk:
    def test_simple_replace(self) -> None:
        lines = ["line1", "line2", "line3"]
        hunk = Hunk(
            old_start=1,
            old_count=3,
            new_start=1,
            new_count=3,
            lines=[
                HunkLine(HunkLineKind.CONTEXT, "line1"),
                HunkLine(HunkLineKind.REMOVE, "line2"),
                HunkLine(HunkLineKind.ADD, "modified"),
                HunkLine(HunkLineKind.CONTEXT, "line3"),
            ],
        )
        apply_hunks_to_lines(lines, [hunk], fuzz=0)
        assert lines == ["line1", "modified", "line3"]

    def test_fuzzy_match(self) -> None:
        """Hunk header says line 2 but actual match is at line 3 → fuzz=1."""
        lines = ["extra_line_0", "line1", "line2", "line3"]
        hunk = Hunk(
            old_start=2,
            old_count=2,
            new_start=2,
            new_count=2,
            lines=[
                HunkLine(HunkLineKind.CONTEXT, "line2"),
                HunkLine(HunkLineKind.REMOVE, "line3"),
                HunkLine(HunkLineKind.ADD, "bye"),
            ],
        )
        stats = apply_hunks_to_lines(lines, [hunk], fuzz=5)
        assert stats.hunks_applied == 1
        assert stats.hunks_with_fuzz == 1
        assert stats.fuzz_used >= 1

    def test_no_match_raises(self) -> None:
        lines = ["line1", "line2"]
        hunk = Hunk(
            old_start=1,
            old_count=1,
            new_start=1,
            new_count=1,
            lines=[
                HunkLine(HunkLineKind.REMOVE, "nope"),
                HunkLine(HunkLineKind.ADD, "whatever"),
            ],
        )
        with pytest.raises(ApplyPatchError, match="Failed to apply hunk"):
            apply_hunks_to_lines(lines, [hunk], fuzz=0)

    def test_append_to_empty(self) -> None:
        """Hunk with no context, adding to empty file."""
        lines: list[str] = []
        hunk = Hunk(
            old_start=0,
            old_count=0,
            new_start=1,
            new_count=2,
            lines=[
                HunkLine(HunkLineKind.ADD, "first"),
                HunkLine(HunkLineKind.ADD, "second"),
            ],
        )
        stats = apply_hunks_to_lines(lines, [hunk])
        assert stats.hunks_applied == 1
        assert lines == ["first", "second"]

    def test_cumulative_offset_two_hunks(self) -> None:
        """Second hunk's expected position shifts because first added lines."""
        lines = [
            "a",
            "b",  # removed by hunk 1
            "c",
            "d",  # removed by hunk 2 (at original line 4, shifted after hunk 1)
            "e",
        ]
        hunk1 = Hunk(
            old_start=2,
            old_count=1,
            new_start=2,
            new_count=2,
            lines=[
                HunkLine(HunkLineKind.REMOVE, "b"),
                HunkLine(HunkLineKind.ADD, "b1"),
                HunkLine(HunkLineKind.ADD, "b2"),
            ],
        )
        # Original line 4 is "d". After hunk1 it's at line 5; hunk.old_start=4
        # expects line 4 but cumulative offset +1 will find it at index 4.
        hunk2 = Hunk(
            old_start=4,
            old_count=1,
            new_start=5,
            new_count=1,
            lines=[
                HunkLine(HunkLineKind.REMOVE, "d"),
                HunkLine(HunkLineKind.ADD, "D"),
            ],
        )
        stats = apply_hunks_to_lines(lines, [hunk1, hunk2], fuzz=0)
        assert stats.hunks_applied == 2
        assert stats.hunks_with_fuzz == 0
        assert lines == ["a", "b1", "b2", "c", "D", "e"]


class TestApplyPatchTool:
    async def test_single_file_patch(self, tmp_path: Path) -> None:
        target = tmp_path / "hello.txt"
        target.write_text("one\ntwo\nthree\n")
        patch = (
            "--- a/hello.txt\n"
            "+++ b/hello.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " one\n"
            "-two\n"
            "+TWO\n"
            " three\n"
        )
        ctx = ToolContext(working_directory=tmp_path)
        result = await ApplyPatchTool().execute({"patch": patch}, ctx)
        assert result.success
        assert result.metadata["files_applied"] == 1
        assert result.metadata["hunks_applied"] == 1
        assert target.read_text() == "one\nTWO\nthree\n"

    async def test_changes_path_creates_file(self, tmp_path: Path) -> None:
        ctx = ToolContext(working_directory=tmp_path)
        result = await ApplyPatchTool().execute(
            {"changes": [{"path": "new.txt", "content": "hello\n"}]},
            ctx,
        )
        assert result.metadata["files_applied"] == 1
        assert (tmp_path / "new.txt").read_text() == "hello\n"

    async def test_path_override(self, tmp_path: Path) -> None:
        target = tmp_path / "x.txt"
        target.write_text("alpha\nbeta\n")
        patch = "@@ -1,2 +1,2 @@\n alpha\n-beta\n+BETA\n"
        ctx = ToolContext(working_directory=tmp_path)
        result = await ApplyPatchTool().execute(
            {"path": "x.txt", "patch": patch}, ctx
        )
        assert result.metadata["hunks_applied"] == 1
        assert target.read_text() == "alpha\nBETA\n"

    async def test_create_if_missing(self, tmp_path: Path) -> None:
        patch = (
            "--- /dev/null\n"
            "+++ b/fresh.txt\n"
            "@@ -0,0 +1,2 @@\n"
            "+hello\n"
            "+world\n"
        )
        ctx = ToolContext(working_directory=tmp_path)
        result = await ApplyPatchTool().execute(
            {"patch": patch, "create_if_missing": True}, ctx
        )
        assert result.success
        assert (tmp_path / "fresh.txt").read_text() == "hello\nworld\n"

    async def test_delete_via_dev_null(self, tmp_path: Path) -> None:
        target = tmp_path / "to_delete.txt"
        target.write_text("bye\n")
        patch = (
            "--- a/to_delete.txt\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-bye\n"
        )
        ctx = ToolContext(working_directory=tmp_path)
        result = await ApplyPatchTool().execute({"patch": patch}, ctx)
        assert result.success
        assert not target.exists()

    async def test_missing_both_rejected(self, tmp_path: Path) -> None:
        ctx = ToolContext(working_directory=tmp_path)
        with pytest.raises(ToolError):
            await ApplyPatchTool().execute({}, ctx)

    async def test_empty_patch_rejected(self, tmp_path: Path) -> None:
        ctx = ToolContext(working_directory=tmp_path)
        with pytest.raises(ToolError):
            await ApplyPatchTool().execute({"patch": "   "}, ctx)

    async def test_missing_file_without_flag_errors(self, tmp_path: Path) -> None:
        patch = (
            "--- a/nope.txt\n"
            "+++ b/nope.txt\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        ctx = ToolContext(working_directory=tmp_path)
        with pytest.raises(ToolError, match="File not found"):
            await ApplyPatchTool().execute({"patch": patch}, ctx)
