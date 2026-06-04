from pathlib import Path

import pytest

from deepseek_tui.evolution.procedural.skill_store import ProceduralSkillStore

_SKILL = """---
name: demo-skill
description: Demo skill for tests
---
# Demo
"""


@pytest.fixture
def skill_store(tmp_path: Path) -> ProceduralSkillStore:
    return ProceduralSkillStore(workspace=tmp_path, default_scope="project")


def test_skill_create_and_patch(skill_store: ProceduralSkillStore, tmp_path: Path) -> None:
    created = skill_store.create("demo-skill", _SKILL)
    assert created.ok
    patched = skill_store.patch("demo-skill", "# Demo", "# Demo v2")
    assert patched.ok
    text = (tmp_path / ".deepseek" / "skills" / "demo-skill" / "SKILL.md").read_text()
    assert "Demo v2" in text


def test_skill_rejects_traversal(skill_store: ProceduralSkillStore) -> None:
    skill_store.create("demo-skill", _SKILL)
    result = skill_store.write_file("demo-skill", "../escape.txt", "nope")
    assert not result.ok


def test_skill_rejects_absolute_path(
    skill_store: ProceduralSkillStore, tmp_path: Path
) -> None:
    skill_store.create("demo-skill", _SKILL)
    outside = tmp_path / "outside.txt"
    result = skill_store.write_file("demo-skill", str(outside), "escaped")
    assert not result.ok
    assert not outside.exists()


def test_skill_patch_supporting_file(skill_store: ProceduralSkillStore) -> None:
    skill_store.create("demo-skill", _SKILL)
    skill_store.write_file("demo-skill", "notes.txt", "version one")
    patched = skill_store.patch(
        "demo-skill",
        "version one",
        "version two",
        file_path="notes.txt",
    )
    assert patched.ok
    root = skill_store.skill_root("demo-skill")
    assert (root / "notes.txt").read_text(encoding="utf-8") == "version two"


def test_skill_patch_miss_returns_preview(skill_store: ProceduralSkillStore) -> None:
    skill_store.create("demo-skill", _SKILL)
    result = skill_store.patch("demo-skill", "missing needle", "x")
    assert not result.ok
    assert result.preview
