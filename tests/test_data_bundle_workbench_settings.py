"""GUI settings.json is included in settings-scoped data bundles."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from deepseek_tui.server.data_bundle import export_bundle, import_bundle


def test_export_import_workbench_settings_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    settings = home / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"version": 1, "theme": "light"}), encoding="utf-8")
    (home / "config.toml").write_text("model = \"x\"\n", encoding="utf-8")

    export_path = tmp_path / "settings.zip"
    report = export_bundle(export_path, scope="settings")
    assert report["files"] >= 3
    with zipfile.ZipFile(export_path) as zf:
        names = set(zf.namelist())
        assert "settings.json" in names
        assert "config.toml" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["includes"]["workbench_settings"] is True

    settings.unlink()
    imported = import_bundle(export_path, mode="replace")
    assert "settings.json" in imported["settings_restored"]
    assert json.loads(settings.read_text(encoding="utf-8"))["theme"] == "light"


def test_import_merge_keeps_existing_workbench_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(home))
    settings = home / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    export_path = tmp_path / "settings.zip"
    export_bundle(export_path, scope="settings")
    settings.write_text(json.dumps({"theme": "kept"}), encoding="utf-8")

    imported = import_bundle(export_path, mode="merge")
    assert "settings.json" not in imported["settings_restored"]
    assert json.loads(settings.read_text(encoding="utf-8"))["theme"] == "kept"
