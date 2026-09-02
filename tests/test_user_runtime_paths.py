"""User-level runtime paths (logs / agents)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config import layout
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


def test_ensure_user_home_layout_preserves_conflicts(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = {
        home / "subagents" / "abc.json": "legacy registry",
        home / "subagent-runs" / "agent_1" / "run.json": "legacy run",
        home / "plugin-host" / "grants" / "grant.json": "legacy grant",
        home / "automations" / "automations" / "job.json": "legacy job",
    }
    current = {
        home / "agents" / "registries" / "abc.json": "current registry",
        home / "agents" / "runs" / "agent_1" / "run.json": "current run",
        home / "plugins" / ".host" / "grants" / "grant.json": "current grant",
        home / "automations" / "job.json": "current job",
    }
    for path, content in {**legacy, **current}.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    ensure_user_home_layout(home)

    assert all(
        path.read_text(encoding="utf-8") == content
        for path, content in current.items()
    )
    quarantined = home / ".migrated-dupes"
    assert sorted(
        path.read_text(encoding="utf-8")
        for path in quarantined.rglob("*.json")
    ) == sorted(legacy.values())


def test_repeated_conflict_gets_unique_quarantine_name(tmp_path: Path) -> None:
    home = tmp_path / "home"
    current = home / "agents" / "registries" / "abc.json"
    legacy = home / "subagents" / "abc.json"
    current.parent.mkdir(parents=True)
    current.write_text("current", encoding="utf-8")

    for content in ("legacy-1", "legacy-2"):
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(content, encoding="utf-8")
        ensure_user_home_layout(home)

    quarantine = home / ".migrated-dupes"
    assert (quarantine / "subagents-abc.json").read_text(encoding="utf-8") == "legacy-1"
    assert (quarantine / "subagents-abc.json.2").read_text(encoding="utf-8") == "legacy-2"
    assert current.read_text(encoding="utf-8") == "current"


def test_interrupted_migration_is_safe_to_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    legacy = home / "subagents"
    legacy.mkdir(parents=True)
    for name in ("a.json", "b.json"):
        (legacy / name).write_text(name, encoding="utf-8")

    original_move = layout.shutil.move
    calls = 0

    def interrupted_move(src: str, dst: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated interruption")
        return original_move(src, dst)

    monkeypatch.setattr(layout.shutil, "move", interrupted_move)
    with pytest.raises(OSError, match="simulated interruption"):
        ensure_user_home_layout(home)

    contents = sorted(
        path.read_text(encoding="utf-8")
        for root in (legacy, home / "agents" / "registries")
        if root.exists()
        for path in root.glob("*.json")
    )
    assert contents == ["a.json", "b.json"]

    monkeypatch.setattr(layout.shutil, "move", original_move)
    ensure_user_home_layout(home)
    assert sorted(
        path.name for path in (home / "agents" / "registries").glob("*.json")
    ) == ["a.json", "b.json"]


def test_backup_metadata_conflict_is_quarantined(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workbench = home / "workbench"
    workbench.mkdir(parents=True)
    (home / "settings.json").write_text(
        '{"backup":{"directory":"current"}}', encoding="utf-8"
    )
    (workbench / "backup-meta.json").write_text(
        '{"directory":"legacy","custom":"preserve-me"}', encoding="utf-8"
    )

    ensure_user_home_layout(home)

    assert '"current"' in (home / "settings.json").read_text(encoding="utf-8")
    quarantined = workbench / ".migrated-dupes" / "backup-meta.json"
    assert '"preserve-me"' in quarantined.read_text(encoding="utf-8")


def test_existing_manifest_is_never_overwritten(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    manifest = home / "MANIFEST.toml"
    customized = 'paths = ["workbench/custom"]\nretention = "forever"\n'
    manifest.write_text(customized, encoding="utf-8")

    ensure_user_home_layout(home)

    assert manifest.read_text(encoding="utf-8") == customized
