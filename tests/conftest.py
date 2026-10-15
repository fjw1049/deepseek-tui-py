"""Shared pytest fixtures — safe engine teardown (no background leak)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.config.paths import user_config_path
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import EngineHandle


@pytest.fixture(autouse=True)
def _isolate_claude_plugins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep plugin discovery off the developer's real ~/.claude/plugins."""
    monkeypatch.setenv("CLAUDE_PLUGINS_DIR", str(tmp_path / "_claude-plugins"))


@pytest.fixture(autouse=True)
def _isolate_deepseek_home(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep threads, run records, agent registries and logs off the real ~/.deepseek.

    ``live`` tests still read the real config (credentials), nothing else.
    """
    if request.node.get_closest_marker("live") is not None:
        monkeypatch.setenv("DEEPSEEK_CONFIG_PATH", str(user_config_path()))
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "_deepseek-home"))


@pytest.fixture
def isolated_config() -> Config:
    """Features on, MCP off — avoids hanging MCP handshakes in tests."""
    return Config(
        features=FeatureConfig(
            tasks=True,
            subagents=True,
            mcp=False,
            automations=False,
        ),
    )


@pytest.fixture
async def engine_ctx(
    tmp_path: Path, isolated_config: Config
) -> AsyncIterator[tuple[Engine, EngineHandle]]:
    """Engine with guaranteed ``shutdown_session`` (no stray coordinator)."""
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle,
        client=AsyncMock(),
        config=isolated_config,
        working_directory=tmp_path,
        task_data_dir=tmp_path / ".deepseek" / "tasks",
    )
    try:
        yield engine, handle
    finally:
        await engine.shutdown_session()
        handle.drain_events()
