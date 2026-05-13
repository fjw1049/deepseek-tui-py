"""Tests for the project_context loader (AGENTS.md / CLAUDE.md / ...).

Mirrors Rust ``project_context.rs`` tests where applicable. Each test
isolates the workspace and ``home_dir`` to ``tmp_path`` so no real file
under ``~/.deepseek`` is read or written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.engine.project_context import (
    MAX_CONTEXT_SIZE,
    PROJECT_CONTEXT_FILES,
    ProjectContext,
    load_project_context,
    load_project_context_with_parents,
)


# ---------------------------------------------------------------------------
# Direct workspace lookup
# ---------------------------------------------------------------------------


def test_load_agents_md_first(tmp_path: Path) -> None:
    """AGENTS.md wins over CLAUDE.md when both exist."""
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("claude body", encoding="utf-8")

    ctx = load_project_context(tmp_path)
    assert ctx.has_instructions()
    assert "agents body" in ctx.instructions
    assert ctx.source_path == tmp_path / "AGENTS.md"


def test_priority_order_falls_through(tmp_path: Path) -> None:
    """When AGENTS.md is missing, .claude/instructions.md wins over CLAUDE.md."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "instructions.md").write_text("claude-style", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("plain claude md", encoding="utf-8")

    ctx = load_project_context(tmp_path)
    assert ctx.has_instructions()
    assert "claude-style" in ctx.instructions
    assert ctx.source_path == tmp_path / ".claude" / "instructions.md"


def test_load_deepseek_instructions_last(tmp_path: Path) -> None:
    """``.deepseek/instructions.md`` is the lowest-priority workspace candidate."""
    (tmp_path / ".deepseek").mkdir()
    (tmp_path / ".deepseek" / "instructions.md").write_text(
        "deepseek-style", encoding="utf-8"
    )

    ctx = load_project_context(tmp_path)
    assert ctx.has_instructions()
    assert "deepseek-style" in ctx.instructions


def test_no_candidates_returns_empty(tmp_path: Path) -> None:
    """Empty workspace → empty context (no warnings)."""
    ctx = load_project_context(tmp_path)
    assert not ctx.has_instructions()
    assert ctx.warnings == []


def test_empty_file_warns_and_skips(tmp_path: Path) -> None:
    """An empty AGENTS.md is treated as missing; loader falls through."""
    (tmp_path / "AGENTS.md").write_text("   \n\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("real content", encoding="utf-8")

    ctx = load_project_context(tmp_path)
    assert ctx.has_instructions()
    assert "real content" in ctx.instructions
    assert any("empty" in w for w in ctx.warnings)


def test_oversized_file_warns_and_skips(tmp_path: Path) -> None:
    """File over MAX_CONTEXT_SIZE is rejected with a warning."""
    big = "x" * (MAX_CONTEXT_SIZE + 1)
    (tmp_path / "AGENTS.md").write_text(big, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("fallback", encoding="utf-8")

    ctx = load_project_context(tmp_path)
    assert ctx.has_instructions()
    assert "fallback" in ctx.instructions
    assert any("too large" in w for w in ctx.warnings)


# ---------------------------------------------------------------------------
# Parent-directory recursion (monorepo)
# ---------------------------------------------------------------------------


def test_parent_recursion_finds_monorepo_root(tmp_path: Path) -> None:
    """When ``workspace`` has no context but a parent does, parent wins."""
    monorepo = tmp_path / "monorepo"
    sub = monorepo / "packages" / "app"
    sub.mkdir(parents=True)
    (monorepo / "AGENTS.md").write_text("monorepo rules", encoding="utf-8")

    ctx = load_project_context_with_parents(sub, home_dir=tmp_path / "no_home")
    assert ctx.has_instructions()
    assert "monorepo rules" in ctx.instructions
    assert ctx.source_path == monorepo / "AGENTS.md"


def test_parent_recursion_stops_at_first_match(tmp_path: Path) -> None:
    """Closer parent wins over farther parent."""
    root = tmp_path / "root"
    mid = root / "mid"
    leaf = mid / "leaf"
    leaf.mkdir(parents=True)
    (root / "AGENTS.md").write_text("root rules", encoding="utf-8")
    (mid / "AGENTS.md").write_text("mid rules", encoding="utf-8")

    ctx = load_project_context_with_parents(leaf, home_dir=tmp_path / "no_home")
    assert "mid rules" in ctx.instructions


# ---------------------------------------------------------------------------
# User-level fallback
# ---------------------------------------------------------------------------


def test_user_level_fallback(tmp_path: Path) -> None:
    """No workspace or parent has context → ``~/.deepseek/AGENTS.md`` wins."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    home = tmp_path / "home"
    (home / ".deepseek").mkdir(parents=True)
    (home / ".deepseek" / "AGENTS.md").write_text("global rules", encoding="utf-8")

    ctx = load_project_context_with_parents(workspace, home_dir=home)
    assert ctx.has_instructions()
    assert "global rules" in ctx.instructions
    assert ctx.source_path == home / ".deepseek" / "AGENTS.md"


# ---------------------------------------------------------------------------
# Auto-generation
# ---------------------------------------------------------------------------


def test_auto_generate_when_nothing_found(tmp_path: Path) -> None:
    """No workspace context + no user context → generate placeholder."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    ctx = load_project_context_with_parents(workspace, home_dir=home)
    assert ctx.has_instructions()
    # Generated file lives on disk for reuse.
    assert (workspace / ".deepseek" / "instructions.md").exists()
    assert "Auto-generated" in ctx.instructions


def test_auto_generate_skips_when_file_exists(tmp_path: Path) -> None:
    """If ``.deepseek/instructions.md`` already exists, it's loaded as-is —
    the empty-workspace path is not taken."""
    workspace = tmp_path / "ws"
    (workspace / ".deepseek").mkdir(parents=True)
    (workspace / ".deepseek" / "instructions.md").write_text(
        "pre-existing", encoding="utf-8"
    )

    ctx = load_project_context_with_parents(workspace, home_dir=tmp_path / "no_home")
    assert ctx.instructions == "pre-existing"


# ---------------------------------------------------------------------------
# System-block formatting
# ---------------------------------------------------------------------------


def test_as_system_block_wraps_with_tags(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("body", encoding="utf-8")
    ctx = load_project_context(tmp_path)
    block = ctx.as_system_block()
    assert block is not None
    assert block.startswith('<project_instructions source="')
    assert "body" in block
    assert block.endswith("</project_instructions>")


def test_as_system_block_returns_none_when_empty(tmp_path: Path) -> None:
    ctx = ProjectContext.empty(tmp_path)
    assert ctx.as_system_block() is None


# ---------------------------------------------------------------------------
# Integration with build_system_prompt
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_project_context(tmp_path: Path) -> None:
    """The system prompt builder injects ``<project_instructions>``."""
    from deepseek_tui.engine.prompts import build_system_prompt

    (tmp_path / "AGENTS.md").write_text("custom rules", encoding="utf-8")
    prompt = build_system_prompt(workspace=tmp_path)

    assert "<project_instructions" in prompt
    assert "custom rules" in prompt
    # Order: project_context before ## Environment
    pi_idx = prompt.index("<project_instructions")
    env_idx = prompt.index("## Environment")
    assert pi_idx < env_idx


def test_build_system_prompt_can_disable_project_context(tmp_path: Path) -> None:
    """``project_context_enabled=False`` skips the loader entirely."""
    from deepseek_tui.engine.prompts import build_system_prompt

    (tmp_path / "AGENTS.md").write_text("never seen", encoding="utf-8")
    prompt = build_system_prompt(workspace=tmp_path, project_context_enabled=False)
    assert "<project_instructions" not in prompt
    assert "never seen" not in prompt


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_priority_list_matches_rust() -> None:
    """Mirror Rust ``PROJECT_CONTEXT_FILES``."""
    assert PROJECT_CONTEXT_FILES == (
        "AGENTS.md",
        ".claude/instructions.md",
        "CLAUDE.md",
        ".deepseek/instructions.md",
    )
