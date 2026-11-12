from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.integrations.skills import (
    SkillRegistry,
    discover_in_workspace,
    skills_directories,
)
from deepseek_tui.tools.knowledge import SkillLoadTool
from deepseek_tui.tools.registry import ToolContext, ToolError


def skill(root, name):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\nBody")


def test_vendor_switch_filters_project_and_home_but_keeps_native(tmp_path, monkeypatch):
    home, workspace = tmp_path / "home", tmp_path / "workspace"
    monkeypatch.setattr(Path, "home", lambda: home)
    for root, name in [
        (home / ".claude/skills", "personal"),
        (workspace / ".claude/skills", "project"),
        (workspace / ".deepseek/skills", "native"),
        (workspace / ".agents/skills", "shared"),
    ]:
        skill(root, name)
    registry = discover_in_workspace(workspace=workspace, disabled_sources=["claude"])
    names = registry.list_names()
    assert "native" in names and "shared" in names
    assert "personal" not in names and "project" not in names
    paths = skills_directories(workspace=workspace, disabled_sources=["claude"])
    assert all(".claude" not in p.parts for p in paths)


async def test_empty_session_registry_does_not_rediscover_disabled_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "deepseek_tui.integrations.skills.discover_in_workspace",
        lambda **kwargs: pytest.fail("Must use frozen empty registry"),
    )
    context = ToolContext(working_directory=tmp_path, metadata={"skill_registry": SkillRegistry()})
    with pytest.raises(ToolError):
        await SkillLoadTool().execute({"name": "disabled"}, context)


async def test_engine_honors_sources_and_custom_directory(tmp_path):
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    skill(tmp_path / ".claude/skills", "disabled")
    skill(tmp_path / "custom", "custom")
    config = Config(
        skills_dir=tmp_path / "custom",
        disabled_skill_sources=["claude"],
        features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False),
    )
    engine = await Engine.create(
        handle=EngineHandle(),
        client=AsyncMock(),
        config=config,
        working_directory=tmp_path,
        start_mcp=False,
    )
    try:
        assert engine.skill_registry.get("custom") is not None
        assert engine.skill_registry.get("disabled") is None
    finally:
        await engine.shutdown_session()
