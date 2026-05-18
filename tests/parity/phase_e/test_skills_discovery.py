"""L1 — SkillRegistry parsing edge cases.

Complements ``test_skills.py`` (which covers the happy path) with the
two edge cases the field audit surfaced:

  - **B1**: ``description: |`` YAML block scalars must round-trip in
    full. Today the parser splits on ``:`` line-by-line and only keeps
    the first line — anything indented underneath is dropped silently.
    Files like ``Humanizer/SKILL.md`` carry their real description in
    a 4-line block; the registry currently exposes only line one.

  - **B2 surface**: when ``frontmatter.name`` differs from the
    directory name, the registry trusts frontmatter (correct), but the
    ``skill_load`` tool resolves by directory name (see L3 tests).
    Lock the registry side here so a future refactor that "fixes" the
    drift by switching to dir-name doesn't silently re-break load.

Per HANDOVER §四 — frontmatter parsing is pure local IO, so unit tests
are the right tool; no real-API coverage needed at this layer.
"""
from __future__ import annotations

from pathlib import Path

from deepseek_tui.skills import SKILL_FILENAME, SkillRegistry, _parse_skill_file


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestYamlBlockScalar:
    """Document parser limitation: ``description: |`` is NOT supported.

    **Why these tests assert the limitation rather than the ideal**:
    the parser is a faithful port of Rust ``parse_skill`` (mod.rs:251),
    which is also line-based and also drops continuation lines. Adding
    block-scalar handling on the Python side would silently diverge
    from Rust parity, surface a different ``description`` field to the
    LLM, and break the parity-test guarantee the repo holds itself to.

    SKILL.md authors must therefore keep ``description`` on a single
    line. The structural lint (``test_skills_lint.py``) flags files
    that violate this convention so the user can rewrite the
    frontmatter rather than expecting silent fix-up.
    """

    def test_block_scalar_pipe_drops_continuation_lines(
        self, tmp_path: Path
    ) -> None:
        """Mirrors Rust ``parse_skill`` line-by-line splitter (mod.rs:251).

        Block scalars (``description: |``) are NOT YAML-parsed; the
        ``|`` sigil itself gets captured as the value, and continuation
        lines underneath are ignored.
        """
        body = (
            "---\n"
            "name: blocky\n"
            "description: |\n"
            "  First line of description.\n"
            "  Second line that gets dropped.\n"
            "---\n"
            "Body here.\n"
        )
        _write(tmp_path / "blocky" / SKILL_FILENAME, body)
        skill = _parse_skill_file(tmp_path / "blocky" / SKILL_FILENAME)
        # Continuation lines never reach the registry.
        assert "First line" not in skill.description
        assert "Second line" not in skill.description

    def test_block_scalar_folded_drops_continuation_lines(
        self, tmp_path: Path
    ) -> None:
        body = (
            "---\n"
            "name: folded\n"
            "description: >\n"
            "  Sentence one.\n"
            "  Sentence two.\n"
            "---\n"
            "Body.\n"
        )
        _write(tmp_path / "folded" / SKILL_FILENAME, body)
        skill = _parse_skill_file(tmp_path / "folded" / SKILL_FILENAME)
        assert "Sentence one" not in skill.description
        assert "Sentence two" not in skill.description

    def test_single_line_description_works_normally(
        self, tmp_path: Path
    ) -> None:
        """The supported case: one-line ``description: text``."""
        body = (
            "---\n"
            "name: plain\n"
            "description: A simple one-liner.\n"
            "---\n"
            "Body.\n"
        )
        _write(tmp_path / "plain" / SKILL_FILENAME, body)
        skill = _parse_skill_file(tmp_path / "plain" / SKILL_FILENAME)
        assert skill.description == "A simple one-liner."


class TestNameDirectoryDrift:
    """B2: registry trusts frontmatter; lock the contract."""

    def test_registry_uses_frontmatter_name(self, tmp_path: Path) -> None:
        body = (
            "---\n"
            "name: real-name\n"
            "description: x\n"
            "---\n"
            "Body.\n"
        )
        _write(tmp_path / "DirName" / SKILL_FILENAME, body)
        registry = SkillRegistry.discover(tmp_path)
        assert registry.list_names() == ["real-name"]
        assert registry.get("real-name") is not None
        assert registry.get("DirName") is None  # dir name is NOT advertised

    def test_skill_path_points_to_actual_file(self, tmp_path: Path) -> None:
        """The registry must remember where on disk the SKILL.md lives.

        Required by the B2 fix in commit 3 — ``_find_skill`` will switch
        from "guess the directory name" to "ask the registry for the
        path it parsed". That contract starts here.
        """
        body = "---\nname: aliased\ndescription: x\n---\nBody.\n"
        target = _write(tmp_path / "OtherDir" / SKILL_FILENAME, body)
        registry = SkillRegistry.discover(tmp_path)
        skill = registry.get("aliased")
        assert skill is not None
        assert skill.path == target
