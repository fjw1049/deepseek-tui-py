"""Unit tests for the search-tool gitignore matcher."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.tools.utils.gitignore import GitIgnoreMatcher


def test_root_gitignore_skips_named_file(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("skip.py\n", encoding="utf-8")
    matcher = GitIgnoreMatcher(tmp_path)
    assert matcher.ignored(tmp_path / "skip.py", is_dir=False)
    assert not matcher.ignored(tmp_path / "keep.py", is_dir=False)


def test_nested_gitignore_and_negation(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / ".gitignore").write_text("!keep.log\n", encoding="utf-8")
    matcher = GitIgnoreMatcher(tmp_path)
    matcher.add_dir(nested)
    assert matcher.ignored(tmp_path / "a.log", is_dir=False)
    assert not matcher.ignored(nested / "keep.log", is_dir=False)


def _matcher(tmp_path: Path, rules: str) -> GitIgnoreMatcher:
    (tmp_path / ".gitignore").write_text(rules, encoding="utf-8")
    return GitIgnoreMatcher(tmp_path)


def test_a_star_does_not_cross_a_directory_boundary(tmp_path: Path) -> None:
    """``fnmatch``'s ``*`` matches ``/``; git's does not.

    Every expectation here was taken from ``git check-ignore`` on a real repo
    with this exact .gitignore. With ``fnmatch`` the nested file was excluded
    too, so the agent silently never saw files git would have shown it — and
    the filtering reported nothing, which made it unfalsifiable from the
    outside.
    """
    matcher = _matcher(tmp_path, "src/*.tmp\n")

    assert matcher.ignored(tmp_path / "src" / "a.tmp", is_dir=False)
    assert not matcher.ignored(tmp_path / "src" / "deep" / "b.tmp", is_dir=False)


def test_double_star_still_crosses_directories(tmp_path: Path) -> None:
    """``**/`` spans zero or more directories, so both depths are ignored."""
    matcher = _matcher(tmp_path, "src/**/*.log\n")

    assert matcher.ignored(tmp_path / "src" / "d.log", is_dir=False)
    assert matcher.ignored(tmp_path / "src" / "deep" / "c.log", is_dir=False)


def test_an_anchored_directory_covers_its_contents(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, "/build\n")

    assert matcher.ignored(tmp_path / "build" / "x.o", is_dir=False)
    assert not matcher.ignored(tmp_path / "src" / "build.py", is_dir=False)


def test_a_bare_name_applies_at_every_depth(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, "node_modules\n")

    assert matcher.ignored(tmp_path / "node_modules" / "pkg" / "i.js", is_dir=False)
    assert matcher.ignored(tmp_path / "a" / "node_modules" / "j.js", is_dir=False)
    assert not matcher.ignored(tmp_path / "src" / "app.js", is_dir=False)


def test_a_question_mark_stays_inside_one_component(tmp_path: Path) -> None:
    matcher = _matcher(tmp_path, "src/?.tmp\n")

    assert matcher.ignored(tmp_path / "src" / "a.tmp", is_dir=False)
    assert not matcher.ignored(tmp_path / "src" / "ab.tmp", is_dir=False)


def test_does_not_walk_up_without_git(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("outer.py\n", encoding="utf-8")
    inner = tmp_path / "ws"
    inner.mkdir()
    (inner / "outer.py").write_text("", encoding="utf-8")
    matcher = GitIgnoreMatcher(inner)
    # No .git above inner, so parent /tmp-style gitignore must not apply.
    assert not matcher.ignored(inner / "outer.py", is_dir=False)
