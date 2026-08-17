"""User-level runtime paths (logs / agents)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.layout import ensure_user_home_layout
from deepseek_tui.config.models import Config, LoggingConfig
from deepseek_tui.config.paths import (
    user_agent_runtime_dir,
    user_logs_dir,
    user_plugin_host_dir,
    user_subagent_runs_dir,
    user_subagents_registries_dir,
    user_subagents_state_path,
    user_thread_plan_path,
    workspace_storage_key,
)


def test_runtime_dirs_under_deepseek_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    assert user_logs_dir() == home / "logs"
    assert user_agent_runtime_dir() == home / "agents"
    assert user_subagent_runs_dir() == home / "agents" / "runs"
    assert user_subagents_registries_dir() == home / "agents" / "registries"
    assert user_plugin_host_dir() == home / "plugins" / ".host"
    assert user_thread_plan_path("thr_abcd1234") == (
        home / "threads" / "plans" / "thr_abcd1234.md"
    )
    with pytest.raises(ValueError):
        user_thread_plan_path("../evil")
    with pytest.raises(ValueError):
        user_thread_plan_path("thr/abcd")


def test_subagents_state_isolated_by_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    a = tmp_path / "proj_a"
    b = tmp_path / "proj_b"
    a.mkdir()
    b.mkdir()
    pa = user_subagents_state_path(a)
    pb = user_subagents_state_path(b)
    assert pa != pb
    assert pa.parent == tmp_path / "home" / "agents" / "registries"
    assert workspace_storage_key(a) == workspace_storage_key(a.resolve())


def test_logging_config_defaults_to_user_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    cfg = Config()
    assert isinstance(cfg.logging, LoggingConfig)
    assert cfg.logging.dir == tmp_path / "home" / "logs"


def test_ensure_user_home_layout_migrates_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    (home / "subagents").mkdir(parents=True)
    (home / "subagents" / "abc.json").write_text("{}", encoding="utf-8")
    (home / "subagent-runs" / "agent_1").mkdir(parents=True)
    (home / "plugin-host" / "grants").mkdir(parents=True)
    (home / "plugin-host" / "grants" / "x.json").write_text("{}", encoding="utf-8")
    nested = home / "automations" / "automations"
    nested.mkdir(parents=True)
    (nested / "job.json").write_text('{"id":"job"}', encoding="utf-8")

    actions = ensure_user_home_layout(home)
    assert any("agents/registries" in a for a in actions)
    assert any("plugins/.host" in a for a in actions)
    assert (home / "agents" / "registries" / "abc.json").is_file()
    assert (home / "agents" / "runs" / "agent_1").is_dir()
    assert (home / "plugins" / ".host" / "grants" / "x.json").is_file()
    assert (home / "automations" / "job.json").is_file()
    assert not (home / "automations" / "automations").exists()
    assert (home / "MANIFEST.toml").is_file()
