from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.errors import InvalidConfigError, UnknownProfileError
from deepseek_tui.config.loader import ConfigLoader


def test_config_loader_reads_file_and_profile(tmp_path: Path) -> None:
    config_file = tmp_path / "deepseek-tui.toml"
    config_file.write_text(
        "\n".join(
            [
                'provider = "deepseek"',
                'model = "base-model"',
                "",
                "[providers.deepseek]",
                'base_url = "https://api.deepseek.com"',
                "",
                "[profiles.work]",
                'model = "work-model"',
            ]
        )
    )

    loaded = ConfigLoader().load(config_path=config_file, profile_name="work")

    assert loaded.provider == "deepseek"
    assert loaded.model == "work-model"
    assert loaded.profile == "work"
    assert loaded.providers["deepseek"].base_url == "https://api.deepseek.com"


def test_config_loader_applies_env_overrides(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "deepseek-tui.toml"
    config_file.write_text('provider = "deepseek"\nmodel = "base-model"\n')
    monkeypatch.setenv("DEEPSEEK_TUI_MODEL", "env-model")
    monkeypatch.setenv("DEEPSEEK_TUI_SHOW_THINKING", "false")

    loaded = ConfigLoader().load(config_path=config_file)

    assert loaded.model == "env-model"
    assert loaded.ui.show_thinking is False


def test_config_loader_applies_cli_overrides(tmp_path: Path) -> None:
    config_file = tmp_path / "deepseek-tui.toml"
    config_file.write_text('provider = "deepseek"\nmodel = "base-model"\n')

    loaded = ConfigLoader().load(config_path=config_file, provider="openai", model="override-model")

    assert loaded.provider == "openai"
    assert loaded.model == "override-model"


def test_config_loader_loads_dotenv_and_project_overlay(tmp_path: Path, monkeypatch) -> None:
    home_config = tmp_path / "config.toml"
    home_config.write_text('provider = "deepseek"\ndefault_text_model = "deepseek-v4-pro"\n')
    project_dir = tmp_path / "project"
    project_config_dir = project_dir / ".deepseek"
    project_config_dir.mkdir(parents=True)
    (project_dir / ".env").write_text("DEEPSEEK_MODEL=env-model\n", encoding="utf-8")
    (project_config_dir / "config.toml").write_text(
        'sandbox_mode = "read-only"\nallow_shell = false\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    loaded = ConfigLoader().load(config_path=home_config, workspace=project_dir)

    assert loaded.model == "env-model"
    assert loaded.sandbox_mode == "read-only"
    assert loaded.allow_shell is False


def test_config_loader_deep_merges_provider_overrides(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "deepseek-tui.toml"
    config_file.write_text(
        "\n".join(
            [
                'provider = "deepseek"',
                "",
                "[providers.deepseek]",
                'base_url = "https://api.deepseek.com"',
                "timeout = 120",
            ]
        )
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-secret")

    loaded = ConfigLoader().load(config_path=config_file)

    assert loaded.providers["deepseek"].base_url == "https://api.deepseek.com"
    assert loaded.providers["deepseek"].timeout == 120
    assert loaded.providers["deepseek"].api_key == "env-secret"


def test_config_loader_rejects_unknown_profile(tmp_path: Path) -> None:
    config_file = tmp_path / "deepseek-tui.toml"
    config_file.write_text('provider = "deepseek"\n')

    with pytest.raises(UnknownProfileError):
        ConfigLoader().load(config_path=config_file, profile_name="missing")


def test_config_loader_rejects_invalid_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "deepseek-tui.toml"
    config_file.write_text("[")

    with pytest.raises(InvalidConfigError):
        ConfigLoader().load(config_path=config_file)
