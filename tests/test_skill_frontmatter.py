"""SKILL.md frontmatter parsing — multiline YAML descriptions."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.integrations.skills import SkillRegistry, _parse_skill_file


def _write_skill(root: Path, name: str, frontmatter: str, body: str = "Body.\n") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return path


def test_parse_skill_folded_description(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path,
        "workflows",
        "name: data-analysis-workflows\n"
        "description: >\n"
        "  Comprehensive data analysis workflows including answering data questions,\n"
        "  exploring datasets, and writing SQL queries.\n",
    )
    skill = _parse_skill_file(path)
    assert skill.name == "data-analysis-workflows"
    assert "Comprehensive data analysis workflows" in skill.description
    assert ">" not in skill.description
    assert "SQL queries" in skill.description


def test_parse_skill_literal_description(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path,
        "comps-valuation",
        "name: comps-valuation\n"
        "description: |\n"
        "  可比公司估值分析工具。\n"
        "  触发词：可比估值、comps、peer comparison\n",
    )
    skill = _parse_skill_file(path)
    assert skill.name == "comps-valuation"
    assert skill.description.startswith("可比公司估值分析工具")
    assert "peer comparison" in skill.description
    assert skill.description.strip() != "|"


def test_parse_skill_allowed_tools_shapes(tmp_path: Path) -> None:
    comma = _write_skill(
        tmp_path,
        "comma",
        "name: comma\ndescription: d\nallowed-tools: read_file, grep\n",
    )
    inline = _write_skill(
        tmp_path,
        "inline",
        "name: inline\ndescription: d\nallowed-tools: [read_file, grep]\n",
    )
    block = _write_skill(
        tmp_path,
        "block",
        "name: block\ndescription: d\nallowed-tools:\n  - read_file\n  - grep\n",
    )
    assert _parse_skill_file(comma).allowed_tools == ("read_file", "grep")
    assert _parse_skill_file(inline).allowed_tools == ("read_file", "grep")
    assert _parse_skill_file(block).allowed_tools == ("read_file", "grep")


def test_registry_discover_keeps_multiline_description(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "check-deck",
        "name: check-deck\n"
        "description: |\n"
        "  Investment banking presentation quality checker.\n"
        "  Use when asked to review pitch decks.\n",
    )
    reg = SkillRegistry.discover(tmp_path)
    assert len(reg.skills) == 1
    assert "Investment banking" in reg.skills[0].description
