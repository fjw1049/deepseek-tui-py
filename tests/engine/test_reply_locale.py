"""Reply language follows config.ui.locale, not message script."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, UiConfig
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator.core import Engine


def test_ui_config_normalizes_legacy_auto_to_zh() -> None:
    assert UiConfig(locale="auto").locale == "zh"
    assert UiConfig(locale="en").locale == "en"
    assert UiConfig().locale == "zh"


@pytest.mark.asyncio
async def test_engine_reply_locale_from_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "ws"
    workspace.mkdir()

    cfg_zh = Config(
        features={"tasks": False, "subagents": False, "mcp": False, "plugins": False},
        ui=UiConfig(locale="zh"),
    )
    engine_zh = await Engine.create(
        EngineHandle(),
        AsyncMock(),
        config=cfg_zh,
        working_directory=workspace,
    )
    try:
        assert engine_zh.reply_locale == "zh"
    finally:
        await engine_zh.shutdown_session()

    cfg_en = Config(
        features={"tasks": False, "subagents": False, "mcp": False, "plugins": False},
        ui=UiConfig(locale="en"),
    )
    engine_en = await Engine.create(
        EngineHandle(),
        AsyncMock(),
        config=cfg_en,
        working_directory=workspace,
    )
    try:
        assert engine_en.reply_locale == "en"
    finally:
        await engine_en.shutdown_session()
