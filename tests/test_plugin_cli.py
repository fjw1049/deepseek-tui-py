from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from deepseek_tui.cli.app import app


def _make_claude_plugin(root: Path, name: str) -> None:
    manifest = root / name / ".claude-plugin"
    manifest.mkdir(parents=True)
    (manifest / "plugin.json").write_text(
        json.dumps({"name": name, "version": "1.0.0"}),
        encoding="utf-8",
    )


def test_plugin_doctor_uses_structured_adapter_report(tmp_path: Path) -> None:
    (tmp_path / ".codebuddy-plugin").mkdir()
    (tmp_path / ".codebuddy-plugin" / "plugin.json").write_text(
        json.dumps({"name": "demo-team", "expertType": "team"}),
        encoding="utf-8",
    )
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "worker.md").write_text(
        "---\nname: worker\ndescription: Worker.\n---\nWork.\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["plugin", "doctor", str(tmp_path)])

    assert result.exit_code == 0
    assert "demo-team [degraded/codebuddy]" in result.stdout
    assert "agent.persona=1" in result.stdout
    assert "CODEBUDDY_TEAM_ORCHESTRATION_DEGRADED" in result.stdout


def test_plugin_install_selects_candidate_from_collection(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "collection"
    _make_claude_plugin(source, "alpha")
    _make_claude_plugin(source, "beta")
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))

    result = CliRunner().invoke(
        app,
        ["plugin", "install", str(source), "--plugin", "beta"],
    )

    assert result.exit_code == 0
    assert "Installed plugin beta" in result.stdout
    assert (tmp_path / "home" / "plugins" / "beta").is_dir()


def test_plugin_install_collection_reports_required_selector(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "collection"
    _make_claude_plugin(source, "alpha")
    _make_claude_plugin(source, "beta")
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))

    result = CliRunner().invoke(app, ["plugin", "install", str(source)])

    assert result.exit_code == 1
    assert "multiple plugin candidates" in result.stdout
