"""Bundled skills ship with the package and resolve via load_skill.

Claude Code's bundled-skills pattern: product-reference skills live
inside the package at the lowest discovery precedence, so any
user-installed skill of the same name overrides them.
"""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.integrations.skills import (
    bundled_skills_dir,
    discover_in_workspace,
    skills_directories,
)


def test_bundled_dir_exists_and_is_last(tmp_path: Path) -> None:
    bundled = bundled_skills_dir()
    assert bundled is not None and bundled.is_dir()
    dirs = skills_directories(workspace=tmp_path)
    assert dirs, "expected at least the bundled directory"
    assert dirs[-1].resolve() == bundled.resolve()


def test_docs_skill_discovered(tmp_path: Path) -> None:
    registry = discover_in_workspace(workspace=tmp_path)
    skill = registry.get("deepseek-tui-docs")
    assert skill is not None
    assert "stale by default" in skill.body


def test_workspace_skill_overrides_bundled(tmp_path: Path) -> None:
    local = tmp_path / ".deepseek" / "skills" / "deepseek-tui-docs"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text(
        "---\nname: deepseek-tui-docs\ndescription: local override\n---\n"
        "local body\n",
        encoding="utf-8",
    )
    registry = discover_in_workspace(workspace=tmp_path)
    skill = registry.get("deepseek-tui-docs")
    assert skill is not None
    assert "local body" in skill.body


def test_base_prompt_routes_product_questions() -> None:
    from deepseek_tui.engine.prompts import build_system_prompt

    prompt = build_system_prompt(project_context_enabled=False)
    assert "deepseek-tui-docs" in prompt
