"""Global + project AGENTS.md merge for system prompt instructions."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.engine.context import load_project_context_with_parents


def test_global_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".deepseek").mkdir(parents=True)
    (home / ".deepseek" / "AGENTS.md").write_text(
        "# Global\noptmem protocol\n", encoding="utf-8"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ctx = load_project_context_with_parents(workspace, home_dir=home)
    assert ctx.has_instructions()
    assert "optmem protocol" in (ctx.instructions or "")
    assert "Auto-generated" not in (ctx.instructions or "")
    assert ctx.source_paths == [home / ".deepseek" / "AGENTS.md"]
    block = ctx.as_system_block()
    assert block is not None
    assert str(home / ".deepseek" / "AGENTS.md") in block


def test_project_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".deepseek").mkdir(parents=True)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("# Project\nbuild with make\n", encoding="utf-8")

    ctx = load_project_context_with_parents(workspace, home_dir=home)
    assert ctx.has_instructions()
    assert "build with make" in (ctx.instructions or "")
    assert "<!-- deepseek: global" not in (ctx.instructions or "")
    assert ctx.source_paths == [workspace / "AGENTS.md"]


def test_global_and_project_merged(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".deepseek").mkdir(parents=True)
    (home / ".deepseek" / "AGENTS.md").write_text(
        "# Global\nMEMORY PROTOCOL\n", encoding="utf-8"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("# Project\nUSE RUST\n", encoding="utf-8")

    ctx = load_project_context_with_parents(workspace, home_dir=home)
    text = ctx.instructions or ""
    assert "MEMORY PROTOCOL" in text
    assert "USE RUST" in text
    assert "<!-- deepseek: global AGENTS.md" in text
    assert "<!-- deepseek: project" in text
    # Global section appears before project section.
    assert text.index("MEMORY PROTOCOL") < text.index("USE RUST")
    assert ctx.source_paths == [
        home / ".deepseek" / "AGENTS.md",
        workspace / "CLAUDE.md",
    ]
    block = ctx.as_system_block()
    assert block is not None
    assert str(home / ".deepseek" / "AGENTS.md") in block
    assert str(workspace / "CLAUDE.md") in block


def test_neither_auto_generates(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".deepseek").mkdir(parents=True)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ctx = load_project_context_with_parents(workspace, home_dir=home)
    assert ctx.has_instructions()
    assert "Auto-generated" in (ctx.instructions or "")
    assert (workspace / ".deepseek" / "instructions.md").is_file()
