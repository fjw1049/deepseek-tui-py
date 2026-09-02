"""Configuration rejects settings that have no runtime behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from deepseek_tui.config.loader import ConfigLoader, read_env_overrides
from deepseek_tui.config.models import Config, InvalidConfigError


@pytest.mark.parametrize(
    "document",
    [
        'tools_file = "tools.json"\n',
        '[auth]\nmode = "api_key"\n',
        '[network]\nenabled = true\ndefault_action = "deny"\n',
        '[server]\nhost = "0.0.0.0"\n',
        '[skills]\nauto_update = true\n',
        '[state]\ndatabase_path = "state.db"\n',
        '[retry]\nmax_retries = 9\n',
        '[ui]\ncolor_scheme = "dark"\n',
        '[notifications]\ninclude_subagent = true\n',
        '[context]\nenabled = false\n',
    ],
)
def test_loader_rejects_unimplemented_fields(tmp_path: Path, document: str) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(document, encoding="utf-8")

    with pytest.raises(InvalidConfigError):
        ConfigLoader().load(config_path=cfg_path, no_project_config=True)


def test_direct_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Config(tools_file=Path("tools.json"))


def test_log_level_env_targets_logging_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_LOG_LEVEL", "DEBUG")
    config = Config.merge_dict(Config(), read_env_overrides())
    assert config.logging.level == "DEBUG"
