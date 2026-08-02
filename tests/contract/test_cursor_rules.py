"""Cursor-configured repos get their rules read, not just their skills.

Skill discovery already scanned `.cursor/skills`, so a repo set up for Cursor
had half its configuration honoured and half silently ignored: the rules the
user wrote to steer the agent never reached the prompt.

Only `alwaysApply: true` rules load. Glob-scoped rules would have to vary the
system prompt with whichever files are in play, and the prompt is ordered
most-static-first precisely so the prefix stays byte-identical and cacheable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.engine.context import (
    load_cursor_rules,
    load_project_context_with_parents,
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """An empty home, so no global AGENTS.md leaks into the merge."""
    h = tmp_path / "home"
    h.mkdir()
    return h


def _rule(workspace: Path, name: str, frontmatter: str, body: str) -> Path:
    rules = workspace / ".cursor" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    path = rules / name
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return path


# --- reading ---------------------------------------------------------------


def test_no_cursor_directory_is_not_an_error(tmp_path: Path) -> None:
    assert load_cursor_rules(tmp_path) == (None, [], [])


def test_an_always_apply_rule_is_loaded(tmp_path: Path) -> None:
    _rule(tmp_path, "style.mdc", "alwaysApply: true", "Use tabs, never spaces.")
    text, paths, warnings = load_cursor_rules(tmp_path)
    assert text is not None and "Use tabs, never spaces." in text
    assert [p.name for p in paths] == ["style.mdc"]
    assert not warnings


def test_a_glob_scoped_rule_is_skipped(tmp_path: Path) -> None:
    _rule(
        tmp_path,
        "ts.mdc",
        "globs: '**/*.ts'\nalwaysApply: false",
        "Prefer const assertions.",
    )
    text, paths, _ = load_cursor_rules(tmp_path)
    assert text is None
    assert paths == []


def test_a_rule_without_frontmatter_is_skipped(tmp_path: Path) -> None:
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "bare.mdc").write_text("just some prose\n", encoding="utf-8")
    assert load_cursor_rules(tmp_path)[0] is None


def test_the_frontmatter_itself_never_reaches_the_prompt(tmp_path: Path) -> None:
    _rule(
        tmp_path,
        "a.mdc",
        "description: internal note\nglobs: '**/*'\nalwaysApply: true",
        "The actual rule.",
    )
    text, _paths, _ = load_cursor_rules(tmp_path)
    assert text is not None
    assert "alwaysApply" not in text
    assert "internal note" not in text
    assert "The actual rule." in text


def test_several_rules_are_ordered_and_labelled(tmp_path: Path) -> None:
    _rule(tmp_path, "b.mdc", "alwaysApply: true", "Second rule.")
    _rule(tmp_path, "a.mdc", "alwaysApply: true", "First rule.")
    text, paths, _ = load_cursor_rules(tmp_path)
    assert text is not None
    assert text.index("First rule.") < text.index("Second rule.")
    assert "a.mdc" in text and "b.mdc" in text
    assert [p.name for p in paths] == ["a.mdc", "b.mdc"]


def test_nested_rule_directories_are_found(tmp_path: Path) -> None:
    nested = tmp_path / ".cursor" / "rules" / "backend"
    nested.mkdir(parents=True)
    (nested / "db.mdc").write_text(
        "---\nalwaysApply: true\n---\n\nNever use raw SQL.\n", encoding="utf-8"
    )
    text, _paths, _ = load_cursor_rules(tmp_path)
    assert text is not None and "Never use raw SQL." in text


def test_broken_frontmatter_warns_instead_of_raising(tmp_path: Path) -> None:
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "bad.mdc").write_text(
        "---\nalwaysApply: [unclosed\n---\n\nbody\n", encoding="utf-8"
    )
    text, paths, warnings = load_cursor_rules(tmp_path)
    assert text is None and paths == []
    assert warnings and "bad.mdc" in warnings[0]


def test_one_broken_rule_does_not_hide_the_others(tmp_path: Path) -> None:
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "a-bad.mdc").write_text(
        "---\nalwaysApply: [unclosed\n---\n\nbody\n", encoding="utf-8"
    )
    _rule(tmp_path, "z-good.mdc", "alwaysApply: true", "Keep this one.")
    text, paths, warnings = load_cursor_rules(tmp_path)
    assert text is not None and "Keep this one." in text
    assert [p.name for p in paths] == ["z-good.mdc"]
    assert warnings


# --- merging into the project block ----------------------------------------


def test_rules_reach_the_system_block(tmp_path: Path, home: Path) -> None:
    _rule(tmp_path, "style.mdc", "alwaysApply: true", "Use tabs.")
    block = load_project_context_with_parents(
        tmp_path, home_dir=home
    ).as_system_block()
    assert block is not None
    assert "Use tabs." in block
    assert block.startswith("<project_instructions")


def test_rules_sit_alongside_agents_md(tmp_path: Path, home: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Run pytest before pushing.\n")
    _rule(tmp_path, "style.mdc", "alwaysApply: true", "Use tabs.")
    ctx = load_project_context_with_parents(tmp_path, home_dir=home)
    assert ctx.instructions is not None
    assert "Run pytest before pushing." in ctx.instructions
    assert "Use tabs." in ctx.instructions
    # AGENTS.md is the project's own file and stays the headline source.
    assert ctx.source_path is not None
    assert ctx.source_path.name == "AGENTS.md"
    assert len(ctx.source_paths) == 2


def test_rules_alone_suppress_the_placeholder(tmp_path: Path, home: Path) -> None:
    """An empty project auto-generates a stub instructions file. A repo whose
    only configuration is Cursor rules is not an empty project."""
    _rule(tmp_path, "style.mdc", "alwaysApply: true", "Use tabs.")
    ctx = load_project_context_with_parents(tmp_path, home_dir=home)
    assert ctx.instructions is not None
    assert "Use tabs." in ctx.instructions
    assert not (tmp_path / ".deepseek" / "instructions.md").exists()


def test_a_project_without_cursor_rules_is_unchanged(
    tmp_path: Path, home: Path
) -> None:
    """The single-layer shape must stay bare — no headers appear just
    because a third layer now exists."""
    (tmp_path / "AGENTS.md").write_text("Run pytest before pushing.\n")
    ctx = load_project_context_with_parents(tmp_path, home_dir=home)
    assert ctx.instructions == "Run pytest before pushing.\n"
