from __future__ import annotations

from pathlib import Path

from deepseek_tui.state.paste_file import (
    LARGE_PASTE_MIN_CHARS,
    is_large_paste,
    mention_for_paste,
    write_paste_txt,
)


def test_small_paste_stays_inline() -> None:
    assert is_large_paste("fix this") is False
    assert is_large_paste("line1\nline2\nline3") is False


def test_many_lines_or_long_text_is_large() -> None:
    assert is_large_paste("\n".join(f"line {i}" for i in range(8))) is True
    assert is_large_paste("x" * LARGE_PASTE_MIN_CHARS) is True
    assert is_large_paste("   ") is False


def test_write_paste_txt_and_mention(tmp_path: Path) -> None:
    path = write_paste_txt("hello dump", tmp_path)
    assert path.parent == tmp_path / ".deepseek" / "pastes"
    assert path.suffix == ".txt"
    assert path.read_text(encoding="utf-8") == "hello dump"
    assert mention_for_paste(path, tmp_path) == f"@{path.relative_to(tmp_path).as_posix()}"


def test_write_paste_txt_unique_names(tmp_path: Path) -> None:
    first = write_paste_txt("one", tmp_path)
    second = write_paste_txt("two", tmp_path)
    assert first != second
    assert first.read_text(encoding="utf-8") == "one"
    assert second.read_text(encoding="utf-8") == "two"
