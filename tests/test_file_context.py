"""Tests for @mention file context expansion."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.state.context import ContextConfig, UserTurnInput, process_turn_input


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "small.py").write_text("def hello():\n    return 42\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Title\n\nBody text.\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_bytes(b"binary\x00bad")
    (tmp_path / "photo.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "docs" / "b.md").write_text("b", encoding="utf-8")
    return tmp_path


class TestParse:
    def test_extract_quoted_mention(self, workspace: Path) -> None:
        raw = 'Please review @"src/small.py" now'
        out = process_turn_input(
            UserTurnInput(raw_text=raw),
            workspace=workspace,
            cwd=workspace,
        )
        assert '"src/small.py"' in out.display_text
        assert "def hello" in out.model_text
        assert out.references[0].kind == "file"
        assert out.references[0].included is True

    def test_multiple_mentions(self, workspace: Path) -> None:
        raw = "@README.md\n@src/small.py\nsummarize"
        out = process_turn_input(
            UserTurnInput(raw_text=raw),
            workspace=workspace,
            cwd=workspace,
        )
        assert len(out.references) == 2
        assert "Local context from @mentions" in out.model_text


class TestResolve:
    def test_absolute_path_outside_workspace(self, workspace: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("outside content", encoding="utf-8")
        raw = f"@{outside}\nread"
        out = process_turn_input(
            UserTurnInput(raw_text=raw),
            workspace=workspace,
            cwd=workspace,
        )
        assert out.references[0].kind == "file"
        assert "outside content" in out.model_text

    def test_missing_file(self, workspace: Path) -> None:
        raw = "@missing.py\nhelp"
        out = process_turn_input(
            UserTurnInput(raw_text=raw),
            workspace=workspace,
            cwd=workspace,
        )
        assert out.references[0].kind == "missing"
        assert "<missing-file" in out.model_text

    def test_directory_listing(self, workspace: Path) -> None:
        raw = "@docs\nlist"
        out = process_turn_input(
            UserTurnInput(raw_text=raw),
            workspace=workspace,
            cwd=workspace,
        )
        assert out.references[0].kind == "directory"
        assert "a.md" in out.model_text
        assert "b.md" in out.model_text


class TestFormats:
    def test_binary_unreadable(self, workspace: Path) -> None:
        raw = "@notes.txt\nfix"
        out = process_turn_input(
            UserTurnInput(raw_text=raw),
            workspace=workspace,
            cwd=workspace,
        )
        assert out.references[0].kind == "binary"
        assert "<unreadable-file" in out.model_text

    def test_media_hint_only(self, workspace: Path) -> None:
        raw = "@photo.png\ndescribe"
        out = process_turn_input(
            UserTurnInput(raw_text=raw),
            workspace=workspace,
            cwd=workspace,
        )
        assert out.references[0].kind == "media"
        assert out.references[0].included is False
        assert "/attach" in out.model_text


class TestLargeFile:
    def test_truncated_inline(self, workspace: Path) -> None:
        big = workspace / "big.txt"
        big.write_text("x" * (150 * 1024), encoding="utf-8")
        cfg = ContextConfig(max_inline_bytes=128 * 1024)
        out = process_turn_input(
            UserTurnInput(raw_text="@big.txt\nread"),
            workspace=workspace,
            cwd=workspace,
            config=cfg,
        )
        assert out.references[0].detail == "truncated"
        assert 'truncated="true"' in out.model_text

    def test_reference_mode(self, workspace: Path) -> None:
        big = workspace / "big.txt"
        big.write_text("y" * (200 * 1024), encoding="utf-8")
        cfg = ContextConfig(large_file_mode="reference", max_inline_bytes=128 * 1024)
        out = process_turn_input(
            UserTurnInput(raw_text="@big.txt\nread"),
            workspace=workspace,
            cwd=workspace,
            config=cfg,
            session_id="test-session",
        )
        assert out.references[0].detail == "reference only"
        assert "<file-reference" in out.model_text
        assert "read_file" in out.model_text


class TestDisplayModelSplit:
    def test_display_stays_raw(self, workspace: Path) -> None:
        raw = "@README.md\nwhat is this?"
        out = process_turn_input(
            UserTurnInput(raw_text=raw),
            workspace=workspace,
            cwd=workspace,
        )
        assert out.display_text == raw
        assert out.model_text.startswith(raw)
        assert "Local context from @mentions" in out.model_text

    def test_no_double_expand(self, workspace: Path) -> None:
        first = process_turn_input(
            UserTurnInput(raw_text="@README.md\nq"),
            workspace=workspace,
            cwd=workspace,
        )
        second = process_turn_input(
            UserTurnInput(raw_text=first.model_text),
            workspace=workspace,
            cwd=workspace,
        )
        assert second.references == []
        assert second.model_text == first.model_text


class TestLimits:
    def test_max_mentions_warning(self, workspace: Path) -> None:
        for i in range(10):
            (workspace / f"f{i}.txt").write_text(f"file{i}", encoding="utf-8")
        mentions = "\n".join(f"@f{i}.txt" for i in range(10))
        cfg = ContextConfig(max_mentions=3)
        out = process_turn_input(
            UserTurnInput(raw_text=f"{mentions}\ngo"),
            workspace=workspace,
            cwd=workspace,
            config=cfg,
        )
        assert len(out.references) == 3
        assert any("first 3" in w for w in out.warnings)
