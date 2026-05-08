"""Skills subsystem parity tests.

Mirrors Rust ``crates/tui/tests/skill_install.rs`` and
``skills/mod.rs`` test coverage.
"""
from __future__ import annotations

from pathlib import Path

from deepseek_tui.skills import (
    SKILL_FILENAME,
    SkillRegistry,
    discover_in_workspace,
    render_available_skills_context,
)
from deepseek_tui.skills.install import (
    InstallOutcome,
    InstallSource,
    RegistryDocument,
    install,
    trust,
    uninstall,
)
from deepseek_tui.skills.system import (
    install_system_skills,
    uninstall_system_skills,
)


def _make_skill(tmp_path: Path, name: str, desc: str = "", body: str = "") -> Path:
    """Create a minimal SKILL.md in a subdirectory."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n"
    (skill_dir / SKILL_FILENAME).write_text(content, encoding="utf-8")
    return skill_dir


class TestSkillParsing:
    def test_parse_with_frontmatter(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "test-skill", "A test skill", "Do stuff.")
        registry = SkillRegistry.discover(tmp_path)
        assert len(registry) == 1
        skill = registry.skills[0]
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert "Do stuff." in skill.body

    def test_parse_without_frontmatter(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bare-skill"
        skill_dir.mkdir()
        (skill_dir / SKILL_FILENAME).write_text(
            "Just a body with no frontmatter.\n", encoding="utf-8"
        )
        registry = SkillRegistry.discover(tmp_path)
        assert len(registry) == 1
        assert registry.skills[0].name == "bare-skill"

    def test_empty_dir_yields_empty_registry(self, tmp_path: Path) -> None:
        registry = SkillRegistry.discover(tmp_path)
        assert registry.is_empty

    def test_nonexistent_dir_yields_empty_registry(self) -> None:
        registry = SkillRegistry.discover(Path("/nonexistent/path"))
        assert registry.is_empty


class TestSkillRegistryLookup:
    def test_get_by_name(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "my-skill", "desc")
        registry = SkillRegistry.discover(tmp_path)
        assert registry.get("my-skill") is not None
        assert registry.get("MY-SKILL") is not None

    def test_get_returns_none_for_unknown(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "known", "desc")
        registry = SkillRegistry.discover(tmp_path)
        assert registry.get("unknown") is None

    def test_list_names(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "alpha", "a")
        _make_skill(tmp_path, "beta", "b")
        registry = SkillRegistry.discover(tmp_path)
        names = registry.list_names()
        assert "alpha" in names
        assert "beta" in names


class TestDiscoverInWorkspace:
    def test_merges_dirs_first_wins(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "skills-a"
        dir_a.mkdir()
        _make_skill(dir_a, "dup", "from A", "body A")

        dir_b = tmp_path / "skills-b"
        dir_b.mkdir()
        _make_skill(dir_b, "dup", "from B", "body B")
        _make_skill(dir_b, "unique-b", "only B", "body unique")

        registry = discover_in_workspace(dir_a, tmp_path)
        names = registry.list_names()
        assert "dup" in names
        dup_skill = registry.get("dup")
        assert dup_skill is not None
        assert "body A" in dup_skill.body


class TestRenderContext:
    def test_renders_skills_block(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "foo", "Do foo things")
        registry = SkillRegistry.discover(tmp_path)
        output = render_available_skills_context(registry)
        assert "foo" in output
        assert "Do foo things" in output
        assert "load_skill" in output

    def test_empty_registry_returns_empty(self) -> None:
        output = render_available_skills_context(SkillRegistry())
        assert output == ""


class TestInstallSource:
    def test_parse_github(self) -> None:
        src = InstallSource.parse("github:owner/repo")
        assert src.kind == "github"
        assert src.owner == "owner"
        assert src.repo == "repo"

    def test_parse_local(self, tmp_path: Path) -> None:
        src = InstallSource.parse(str(tmp_path))
        assert src.kind == "local"

    def test_parse_invalid(self) -> None:
        src = InstallSource.parse("not-a-valid-source")
        assert src.kind == "invalid"


class TestInstallLocal:
    def test_install_local_skill(self, tmp_path: Path) -> None:
        source_dir = _make_skill(tmp_path / "source", "local-skill", "local")
        install_dir = tmp_path / "installed"
        install_dir.mkdir()

        src = InstallSource.parse(str(source_dir))
        outcome, msg = install(src, skills_dir=install_dir)
        assert outcome == InstallOutcome.INSTALLED
        assert (install_dir / "local-skill" / SKILL_FILENAME).exists()
        assert (install_dir / "local-skill" / ".installed-from").exists()

    def test_install_rejects_duplicate(self, tmp_path: Path) -> None:
        source_dir = _make_skill(tmp_path / "source", "dup-skill", "dup")
        install_dir = tmp_path / "installed"
        install_dir.mkdir()

        src = InstallSource.parse(str(source_dir))
        install(src, skills_dir=install_dir)
        outcome, _ = install(src, skills_dir=install_dir)
        assert outcome == InstallOutcome.ALREADY_EXISTS

    def test_install_rejects_no_skill_md(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        src = InstallSource.parse(str(empty_dir))
        outcome, msg = install(src, skills_dir=tmp_path / "installed")
        assert outcome == InstallOutcome.FAILED


class TestUninstall:
    def test_uninstall_community_skill(self, tmp_path: Path) -> None:
        source_dir = _make_skill(tmp_path / "source", "to-remove", "rm")
        install_dir = tmp_path / "installed"
        install_dir.mkdir()
        src = InstallSource.parse(str(source_dir))
        install(src, skills_dir=install_dir)

        msg = uninstall("to-remove", skills_dir=install_dir)
        assert "Uninstalled" in msg
        assert not (install_dir / "to-remove").exists()

    def test_uninstall_rejects_system_skill(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "system-skill")
        msg = uninstall("system-skill", skills_dir=tmp_path)
        assert "Cannot uninstall" in msg

    def test_uninstall_missing_skill(self, tmp_path: Path) -> None:
        msg = uninstall("nonexistent", skills_dir=tmp_path)
        assert "not found" in msg


class TestTrust:
    def test_trust_community_skill(self, tmp_path: Path) -> None:
        source_dir = _make_skill(tmp_path / "source", "to-trust", "t")
        install_dir = tmp_path / "installed"
        install_dir.mkdir()
        src = InstallSource.parse(str(source_dir))
        install(src, skills_dir=install_dir)

        msg = trust("to-trust", skills_dir=install_dir)
        assert "Trusted" in msg
        assert (install_dir / "to-trust" / ".trusted").exists()

    def test_trust_rejects_non_community(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "manual-skill")
        msg = trust("manual-skill", skills_dir=tmp_path)
        assert "not a community install" in msg


class TestSystemSkills:
    def test_install_creates_skill_creator(self, tmp_path: Path) -> None:
        install_system_skills(tmp_path)
        assert (tmp_path / "skill-creator" / SKILL_FILENAME).exists()
        assert (tmp_path / "skill-creator" / ".system-installed-version").exists()

    def test_install_idempotent(self, tmp_path: Path) -> None:
        install_system_skills(tmp_path)
        content1 = (tmp_path / "skill-creator" / SKILL_FILENAME).read_text()
        install_system_skills(tmp_path)
        content2 = (tmp_path / "skill-creator" / SKILL_FILENAME).read_text()
        assert content1 == content2

    def test_uninstall_removes_skill_creator(self, tmp_path: Path) -> None:
        install_system_skills(tmp_path)
        uninstall_system_skills(tmp_path)
        assert not (tmp_path / "skill-creator").exists()


class TestRegistryDocument:
    def test_parse_registry_json(self) -> None:
        raw = '{"skills": {"foo": {"source": "github:a/b", "description": "Foo"}}}'
        doc = RegistryDocument.from_json(raw)
        assert "foo" in doc.skills
        assert doc.skills["foo"].source == "github:a/b"
        assert doc.skills["foo"].description == "Foo"

    def test_parse_empty(self) -> None:
        doc = RegistryDocument.from_json("{}")
        assert len(doc.skills) == 0
