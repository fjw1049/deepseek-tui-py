from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.plugins.adapters import inspect_local_source
from deepseek_tui.plugins.model import CompatibilityStatus, ResourceRef
from deepseek_tui.plugins.source import PluginSourceError


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_claude_adapter_inspects_conventional_layout_and_real_yaml(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "skills" / "review" / "SKILL.md",
        "---\nname: review\ndescription: >-\n  Review code carefully.\n---\nBody.\n",
    )
    _write(tmp_path / "commands" / "hello.md", "Say hello to $ARGUMENTS.\n")
    _write(
        tmp_path / "agents" / "worker.md",
        "---\nname: worker\ndescription: Worker.\ntools:\n  - Read\n  - Grep\n---\nDo it.\n",
    )
    _write(tmp_path / "hooks" / "hooks.json", json.dumps({"hooks": {}}))
    _write(tmp_path / ".mcp.json", json.dumps({"mcpServers": {}}))

    packages, diagnostics = inspect_local_source(tmp_path)

    assert diagnostics == ()
    assert len(packages) == 1
    package = packages[0]
    assert package.compatibility.status is CompatibilityStatus.NATIVE
    assert {(item.kind, item.name) for item in package.contributions} >= {
        ("prompt.skill", "review"),
        ("prompt.command", "hello"),
        ("agent.persona", "worker"),
        ("lifecycle.hook", "hooks"),
        ("runtime.mcp-server", "mcp"),
    }
    worker = next(item for item in package.contributions if item.name == "worker")
    assert worker.metadata["tools"] == ["Read", "Grep"]


def test_collection_locator_keeps_nested_plugin_collision_visible(tmp_path: Path) -> None:
    for relative, marker in (
        ("suite", ".deepseek-plugin"),
        ("suite/expert", ".claude-plugin"),
    ):
        _write(
            tmp_path / relative / marker / "plugin.json",
            json.dumps({"name": "same-suite", "version": "1.0.0"}),
        )
    _write(
        tmp_path / "standalone" / "SKILL.md",
        "---\nname: standalone\ndescription: Standalone.\n---\nBody.\n",
    )
    _write(
        tmp_path / "suite" / "skills" / "inner" / "SKILL.md",
        "---\nname: inner\ndescription: Inner.\n---\nBody.\n",
    )

    packages, diagnostics = inspect_local_source(tmp_path)

    assert len(packages) == 3
    assert [item.plugin_id for item in packages].count("same-suite") == 2
    assert [item.plugin_id for item in packages].count("inner") == 0
    assert any(item.code == "PLUGIN_ID_COLLISION" for item in diagnostics)


def test_marketplace_locator_uses_local_entries_and_reports_remote(tmp_path: Path) -> None:
    _write(
        tmp_path / ".claude-plugin" / "marketplace.json",
        json.dumps(
            {
                "plugins": [
                    {"name": "local", "source": "./plugins/local"},
                    {
                        "name": "remote",
                        "source": {
                            "source": "git-subdir",
                            "url": "https://example.com/repo.git",
                            "path": "plugin",
                        },
                    },
                ]
            }
        ),
    )
    _write(
        tmp_path / "plugins" / "local" / ".claude-plugin" / "plugin.json",
        json.dumps({"name": "local", "version": "1.0.0"}),
    )
    _write(
        tmp_path / "plugins" / "local" / "commands" / "run.md",
        "Run.\n",
    )

    packages, diagnostics = inspect_local_source(tmp_path)

    assert [item.plugin_id for item in packages] == ["local", "remote"]
    assert packages[1].compatibility.status is CompatibilityStatus.BLOCKED
    assert packages[1].compatibility.can_install is True
    assert packages[1].compatibility.can_activate is False
    assert any(item.code == "REMOTE_MARKETPLACE_SOURCE_NOT_FETCHED" for item in diagnostics)


def test_pi_package_is_not_recognized(tmp_path: Path) -> None:
    """``package.json#pi.extensions`` alone is not a supported plugin format."""
    _write(
        tmp_path / "package.json",
        json.dumps(
            {
                "name": "@example/pi-computer-use",
                "version": "0.4.3",
                "engines": {"node": ">=20.6.0"},
                "scripts": {"postinstall": "node setup.mjs"},
                "pi": {"extensions": ["./extensions"]},
            }
        ),
    )
    _write(tmp_path / "extensions" / "computer-use.ts", "export default {}\n")

    packages, diagnostics = inspect_local_source(tmp_path)

    assert packages == ()
    assert not any(
        getattr(item, "adapter_id", None) == "pi-package" for item in packages
    )
    # No candidate roots → no adapter probe; may be empty diagnostics.
    assert all(item.code != "AMBIGUOUS_PLUGIN_ADAPTER" for item in diagnostics)


@pytest.mark.parametrize("path", ["../escape", "/absolute", r"nested\escape"])
def test_resource_ref_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError):
        ResourceRef(path)


def test_local_inspection_accepts_internal_file_symlink(tmp_path: Path) -> None:
    """Real Claude plugins ship internal symlinks (AGENTS.md -> CLAUDE.md);
    these resolve inside the plugin root and must not be rejected."""
    _write(
        tmp_path / ".claude-plugin" / "plugin.json",
        json.dumps({"name": "linked", "version": "1.0.0"}),
    )
    _write(tmp_path / "CLAUDE.md", "Guidance.\n")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")

    packages, _ = inspect_local_source(tmp_path)

    assert [item.plugin_id for item in packages] == ["linked"]


def test_local_inspection_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-plugin-file"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "escaped").symlink_to(outside)

    with pytest.raises(PluginSourceError, match="symlinks"):
        inspect_local_source(tmp_path)
