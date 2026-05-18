"""L3 — ``load_skill`` tool wiring.

Aligned with Rust ``LoadSkillTool`` (tools/skill.rs). Five behaviours
the tool must guarantee:

  1. ``path=`` (explicit) reads the given file verbatim.
  2. ``name=`` resolves via ``discover_in_workspace`` so the registry
     is the single source of truth — works across every directory
     ``skills_directories`` advertises (workspace overlays + user
     globals).
  3. Name/directory drift (frontmatter ``name: foo`` in dir ``Bar/``)
     resolves cleanly because the registry stores the real on-disk
     ``skill.path``.
  4. Legacy ``skill_name=`` alias still works (back-compat with prompts
     cached against the pre-rename Python tool).
  5. Tool result body matches Rust ``format_skill_body``: ``# Skill:``
     header, blockquoted description, ``Source:`` line, ``## SKILL.md``
     section, and a ``## Companion files`` listing when siblings exist.

Negative path: unknown name → error message lists Available skills
(Rust parity, skill.rs:108).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deepseek_tui.skills import SKILL_FILENAME
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.knowledge_tools import SkillLoadTool


def _write_skill(root: Path, dir_name: str, *, name: str | None = None,
                 description: str = "test", body: str = "Body line.") -> Path:
    fm_name = name if name is not None else dir_name
    skill_dir = root / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    md = skill_dir / SKILL_FILENAME
    md.write_text(
        f"---\nname: {fm_name}\ndescription: {description}\n---\n{body}\n",
        encoding="utf-8",
    )
    return md


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home()`` so user-level skills lookup is sandboxed."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _run(coro):
    return asyncio.run(coro)


def test_tool_name_is_load_skill() -> None:
    """Mirror Rust ``LoadSkillTool::name`` (skill.rs:41).

    The tool name is the literal string the model emits to invoke it.
    The system-prompt skills section advertises ``load_skill(name=...)``
    — keep these two in lockstep.
    """
    assert SkillLoadTool().name() == "load_skill"


class TestExplicitPath:
    def test_loads_by_path(self, workspace: Path, tmp_path: Path) -> None:
        target = _write_skill(tmp_path / "anywhere", "raw",
                              body="EXPLICIT_BODY_TOKEN")
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"path": str(target)}, ctx))
        assert result.success
        assert "EXPLICIT_BODY_TOKEN" in result.content


class TestNameResolution:
    """Every directory the registry advertises must be loadable by name."""

    def test_resolves_project_skill(self, workspace: Path,
                                    isolated_home: Path) -> None:
        _write_skill(workspace / ".deepseek" / "skills", "proj-skill",
                     body="PROJ_TOKEN")
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"name": "proj-skill"}, ctx))
        assert result.success
        assert "PROJ_TOKEN" in result.content

    def test_resolves_user_skill(self, workspace: Path,
                                 isolated_home: Path) -> None:
        """User-level ``~/.deepseek/skills`` must be reachable.

        Was broken pre-fix: ``_find_skill`` only walked the workspace
        candidate. Now resolved via ``discover_in_workspace`` + the
        registry's path field.
        """
        _write_skill(isolated_home / ".deepseek" / "skills", "user-skill",
                     body="USER_TOKEN")
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"name": "user-skill"}, ctx))
        assert result.success
        assert "USER_TOKEN" in result.content

    def test_resolves_claude_overlay_skill(self, workspace: Path,
                                           isolated_home: Path) -> None:
        _write_skill(isolated_home / ".claude" / "skills", "claude-skill",
                     body="CLAUDE_TOKEN")
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"name": "claude-skill"}, ctx))
        assert result.success
        assert "CLAUDE_TOKEN" in result.content


class TestNameDirectoryDrift:
    """Frontmatter name may differ from directory — registry remembers
    the real on-disk path, so lookup still succeeds."""

    def test_loads_by_frontmatter_name_when_dir_differs(
        self, workspace: Path, isolated_home: Path
    ) -> None:
        _write_skill(
            isolated_home / ".deepseek" / "skills",
            "Humanizer",
            name="humanizer-zh",
            body="HUMANIZER_TOKEN",
        )
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"name": "humanizer-zh"}, ctx))
        assert result.success
        assert "HUMANIZER_TOKEN" in result.content


class TestLegacyAlias:
    """Pre-rename param name ``skill_name`` still works."""

    def test_skill_name_alias(self, workspace: Path,
                              isolated_home: Path) -> None:
        _write_skill(isolated_home / ".deepseek" / "skills", "aliased",
                     body="ALIAS_TOKEN")
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"skill_name": "aliased"}, ctx))
        assert result.success
        assert "ALIAS_TOKEN" in result.content


class TestErrorHint:
    """Mirror Rust skill.rs:108 — unknown name lists Available skills."""

    def test_unknown_name_lists_available(
        self, workspace: Path, isolated_home: Path
    ) -> None:
        from deepseek_tui.tools.base import ToolError
        _write_skill(isolated_home / ".deepseek" / "skills", "alpha",
                     body="A")
        _write_skill(isolated_home / ".deepseek" / "skills", "beta",
                     body="B")
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        with pytest.raises(ToolError) as ei:
            _run(tool.execute({"name": "nope"}, ctx))
        msg = str(ei.value)
        assert "nope" in msg
        assert "Available" in msg
        assert "alpha" in msg and "beta" in msg

    def test_no_skills_installed_hint(
        self, workspace: Path, isolated_home: Path
    ) -> None:
        from deepseek_tui.tools.base import ToolError
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        with pytest.raises(ToolError) as ei:
            _run(tool.execute({"name": "missing"}, ctx))
        msg = str(ei.value)
        assert "no skills" in msg.lower() or "missing" in msg


class TestFormattedBody:
    """Mirror Rust ``format_skill_body`` (skill.rs:134)."""

    def test_body_includes_header_description_source(
        self, workspace: Path, isolated_home: Path
    ) -> None:
        _write_skill(
            isolated_home / ".deepseek" / "skills",
            "fancy",
            description="A fancy skill marker_zzz9",
            body="# Steps\n1. Do thing.\n",
        )
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"name": "fancy"}, ctx))
        assert "# Skill: fancy" in result.content
        assert "> A fancy skill marker_zzz9" in result.content
        assert "Source: `" in result.content
        assert "## SKILL.md" in result.content
        assert "1. Do thing." in result.content


class TestCompanionFiles:
    """Mirror Rust ``collect_companion_files`` (skill.rs:162)."""

    def test_companion_section_lists_siblings(
        self, workspace: Path, isolated_home: Path
    ) -> None:
        skills_root = isolated_home / ".deepseek" / "skills"
        md_path = _write_skill(skills_root, "rich-skill", body="body")
        (md_path.parent / "script.py").write_text("print('hi')\n")
        (md_path.parent / "data.json").write_text("{}\n")
        # Nested directory must be skipped.
        (md_path.parent / "nested").mkdir()
        (md_path.parent / "nested" / "ignored.txt").write_text("nope\n")

        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"name": "rich-skill"}, ctx))
        assert "## Companion files" in result.content
        assert "script.py" in result.content
        assert "data.json" in result.content
        # Nested files are not listed.
        assert "ignored.txt" not in result.content
        # SKILL.md itself is not listed as a companion bullet.
        assert "- `" in result.content
        companion_section = result.content.split("## Companion files", 1)[1]
        assert "SKILL.md" not in companion_section
        # Metadata exposes the same list for downstream consumers.
        assert any(
            p.endswith("script.py") for p in result.metadata["companion_files"]
        )

    def test_no_companion_section_when_alone(
        self, workspace: Path, isolated_home: Path
    ) -> None:
        _write_skill(isolated_home / ".deepseek" / "skills", "lonely",
                     body="body")
        tool = SkillLoadTool()
        ctx = ToolContext(working_directory=workspace)
        result = _run(tool.execute({"name": "lonely"}, ctx))
        assert "## Companion files" not in result.content
