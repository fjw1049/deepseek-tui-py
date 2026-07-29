"""User-level runtime paths (logs / workflow / agents)."""

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
    user_workflow_runs_dir,
    workspace_storage_key,
)
from deepseek_tui.workflow.store import workflow_runs_dir


def test_runtime_dirs_under_deepseek_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    assert user_logs_dir() == home / "logs"
    assert user_workflow_runs_dir() == home / "workflow"
    assert user_agent_runtime_dir() == home / "agents"
    assert user_subagent_runs_dir() == home / "agents" / "runs"
    assert user_subagents_registries_dir() == home / "agents" / "registries"
    assert user_plugin_host_dir() == home / "plugins" / ".host"
    assert workflow_runs_dir(tmp_path / "repo") == home / "workflow"


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


def test_ensure_user_home_layout_renames_workflow_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    run = home / "workflow-runs" / "wf_abc"
    run.mkdir(parents=True)
    (run / "run.json").write_text("{}", encoding="utf-8")

    actions = ensure_user_home_layout(home)
    assert any("workflow-runs/" in a and "workflow/" in a for a in actions)
    assert (home / "workflow" / "wf_abc" / "run.json").is_file()
    assert not (home / "workflow-runs").exists()
    assert "workflow-runs/" not in (home / "MANIFEST.toml").read_text(encoding="utf-8")


def test_workflow_migrate_quarantines_duplicate_run_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    kept = home / "workflow" / "wf_dup"
    kept.mkdir(parents=True)
    (kept / "run.json").write_text('{"side":"new"}', encoding="utf-8")
    legacy = home / "workflow-runs" / "wf_dup"
    legacy.mkdir(parents=True)
    (legacy / "run.json").write_text('{"side":"legacy"}', encoding="utf-8")

    actions = ensure_user_home_layout(home)
    assert any("quarantined" in a for a in actions)
    assert (home / "workflow" / "wf_dup" / "run.json").read_text(encoding="utf-8") == (
        '{"side":"new"}'
    )
    quarantined = home / "workflow" / ".migrated-dupes" / "wf_dup" / "run.json"
    assert quarantined.is_file()
    assert quarantined.read_text(encoding="utf-8") == '{"side":"legacy"}'
    assert not (home / "workflow-runs").exists()
