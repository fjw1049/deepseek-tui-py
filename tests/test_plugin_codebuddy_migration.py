"""One-time CodeBuddy → canonical layout migration."""

from __future__ import annotations

import json
from pathlib import Path

from deepseek_tui.integrations.plugins import (
    collect_contributions,
    discover_plugins,
    load_plugin_manifest,
    migrate_codebuddy_plugins,
    read_lockfile,
    set_plugin_trusted,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def make_codebuddy_install(plugins_dir: Path) -> None:
    # Plugin with agentName/expertType + hooks using CODEBUDDY tokens
    # (mirrors ppt-implement).
    ppt = plugins_dir / "ppt"
    _write_json(
        ppt / ".codebuddy-plugin" / "plugin.json",
        {
            "name": "ppt",
            "version": "1.0.0",
            "agents": ["./agents/expert.md"],
            "hooks": "./hooks/hooks.json",
            "expertType": "agent",
            "agentName": "expert",
            "category": "tool",
        },
    )
    (ppt / "agents").mkdir()
    (ppt / "agents" / "expert.md").write_text(
        "---\nname: expert\ndescription: e\n---\nBody.\n", encoding="utf-8"
    )
    _write_json(
        ppt / "hooks" / "hooks.json",
        {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'node "${CODEBUDDY_PLUGIN_ROOT}/x.js" '
                                '"${CODEBUDDY_PROJECT_DIR}"',
                            }
                        ]
                    }
                ]
            }
        },
    )
    # Plugin whose manifest name differs from its directory
    # (mirrors document-process / document-skills).
    doc = plugins_dir / "document-process"
    _write_json(
        doc / ".codebuddy-plugin" / "plugin.json",
        {"name": "document-skills", "version": "1.0.0"},
    )
    skill = doc / "skills" / "docx"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: docx\ndescription: d\n---\nBody.\n", encoding="utf-8"
    )
    # Lockfile with the manifest-name key, a dead entry, and an
    # incomplete entry (mirrors equity-research / warp).
    _write_json(
        plugins_dir / "installed_plugins.json",
        {
            "version": 1,
            "plugins": {
                "ppt": {
                    "source": "/nonexistent/staging/ppt",
                    "enabled": True,
                    "trusted": True,
                    "derived_provenance": {"adapter_id": "codebuddy"},
                },
                "document-skills": {
                    "source": "/nonexistent/document-skills",
                    "enabled": True,
                    "trusted": False,
                },
                "equity-research": {
                    "source": "/nonexistent/equity-research",
                    "enabled": True,
                    "trusted": True,
                },
                "warp": {"source": None},
            },
        },
    )


def test_migration_full_pass(tmp_path: Path) -> None:
    make_codebuddy_install(tmp_path)
    report = migrate_codebuddy_plugins(plugins_dir=tmp_path)
    text = "\n".join(report)

    # Manifests moved to the canonical location.
    for name in ("ppt", "document-process"):
        assert not (tmp_path / name / ".codebuddy-plugin").exists()
        assert (tmp_path / name / ".deepseek-plugin" / "plugin.json").is_file()

    # agentName → settings.json defaultAgent; CodeBuddy keys dropped.
    settings = json.loads(
        (tmp_path / "ppt" / "settings.json").read_text(encoding="utf-8")
    )
    assert settings["defaultAgent"] == "expert"
    manifest_data = json.loads(
        (tmp_path / "ppt" / ".deepseek-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    for key in ("agentName", "expertType", "category"):
        assert key not in manifest_data

    # Manifest surface: defaultAgent resolves from settings.json.
    manifest = load_plugin_manifest(tmp_path / "ppt")
    assert manifest is not None and manifest.default_agent == "expert"

    # Name normalized to the directory name.
    doc_manifest = load_plugin_manifest(tmp_path / "document-process")
    assert doc_manifest is not None and doc_manifest.name == "document-process"

    # CODEBUDDY tokens rewritten to CLAUDE equivalents.
    hooks_text = (tmp_path / "ppt" / "hooks" / "hooks.json").read_text(
        encoding="utf-8"
    )
    assert "CODEBUDDY" not in hooks_text
    assert "${CLAUDE_PLUGIN_ROOT}" in hooks_text

    # Lockfile: re-keyed, sources repointed, dead entries pruned,
    # provenance dropped, index rebuilt.
    lock = read_lockfile(tmp_path)
    assert set(lock) == {"ppt", "document-process"}
    assert lock["ppt"]["source"] == str(tmp_path / "ppt")
    assert "derived_provenance" not in lock["ppt"]
    assert lock["ppt"]["contribution_index"]["agents"]
    assert "equity-research" in text and "warp" in text

    # Trusted plugin stays trusted (grant re-bound).
    assert lock["ppt"].get("trusted") is True

    # Post-migration discovery works and hooks load with claude dialect.
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    events = {h.event: h for h in contribs.hook_entries}
    assert "turn_end" in events
    assert events["turn_end"].io_dialect == "claude"
    assert "${CLAUDE_PLUGIN_ROOT}" not in events["turn_end"].command
    assert "${DEEPSEEK_WORKSPACE}" in events["turn_end"].command


def test_migration_idempotent(tmp_path: Path) -> None:
    make_codebuddy_install(tmp_path)
    migrate_codebuddy_plugins(plugins_dir=tmp_path)
    report = migrate_codebuddy_plugins(plugins_dir=tmp_path)
    assert any("nothing to do" in line.lower() for line in report)


def test_migration_no_dir(tmp_path: Path) -> None:
    report = migrate_codebuddy_plugins(plugins_dir=tmp_path / "missing")
    assert any("nothing to migrate" in line.lower() for line in report)


def test_migration_preserves_untrusted_state(tmp_path: Path) -> None:
    make_codebuddy_install(tmp_path)
    migrate_codebuddy_plugins(plugins_dir=tmp_path)
    lock = read_lockfile(tmp_path)
    assert lock["document-process"].get("trusted") is False
    # And trusting after migration works against the new layout.
    msg = set_plugin_trusted("document-process", True, plugins_dir=tmp_path)
    assert "Trusted" in msg
