"""Config loader warns on known unconsumed fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.warnings import warn_unconsumed_config_fields


def test_warn_tools_file(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    from deepseek_tui.config.models import Config

    cfg = Config(tools_file=tmp_path / "tools.json")
    with caplog.at_level("WARNING"):
        warn_unconsumed_config_fields(cfg)
    assert any("tools_file" in r.message for r in caplog.records)


def test_loader_warns_on_tools_file_in_toml(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(f'tools_file = "{tmp_path / "t.json"}"\n', encoding="utf-8")
    with caplog.at_level("WARNING"):
        ConfigLoader().load(config_path=cfg_path, no_project_config=True)
    assert any("tools_file" in r.message for r in caplog.records)
