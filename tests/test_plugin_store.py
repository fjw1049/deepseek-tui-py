from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.plugins.host import InstallPlugin, PluginHost
from deepseek_tui.plugins.store import publish_source_tree, source_path


def test_publish_source_tree_is_content_addressed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("---\nname: a\n---\nbody\n", encoding="utf-8")
    digest, path = publish_source_tree(src)
    assert digest.startswith("sha256:")
    assert path == source_path(digest)
    assert (path / "SKILL.md").is_file()
    # Second publish is a no-op hit.
    digest2, path2 = publish_source_tree(src)
    assert digest2 == digest
    assert path2 == path


def test_install_links_into_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    src = tmp_path / "plugin"
    src.mkdir()
    manifest = src / ".claude-plugin"
    manifest.mkdir()
    (manifest / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0", "skills": "./skills"}),
        encoding="utf-8",
    )
    skill = src / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: d\n---\nBody\n", encoding="utf-8"
    )
    result = PluginHost().apply(
        InstallPlugin(source=str(src), plugins_dir=tmp_path / "installed")
    )
    assert result.outcome == "installed"
    dest = tmp_path / "installed" / "demo"
    assert dest.exists()
    # Prefer symlink into store when the platform allows it.
    if dest.is_symlink():
        assert "plugin-host" in str(dest.resolve())


def test_gc_removes_unreferenced_digest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    src = tmp_path / "orphan"
    src.mkdir()
    (src / "SKILL.md").write_text("---\nname: orphan\n---\nx\n", encoding="utf-8")
    digest, path = publish_source_tree(src)
    assert path.is_dir()
    from deepseek_tui.plugins.host import GcPlugins
    from deepseek_tui.plugins.store import gc_unreferenced_sources

    removed = gc_unreferenced_sources(dry_run=True)
    assert digest.removeprefix("sha256:") in removed or any(
        d in digest for d in removed
    )
    result = PluginHost().apply(GcPlugins(dry_run=False))
    assert result.outcome == "gc"
    assert not source_path(digest).exists()


def test_rollback_relinks_to_prior_digest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    v1 = tmp_path / "v1"
    v1.mkdir()
    (v1 / ".claude-plugin").mkdir()
    (v1 / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0"}), encoding="utf-8"
    )
    (v1 / "marker.txt").write_text("one", encoding="utf-8")
    digest1, _ = publish_source_tree(v1)
    v2 = tmp_path / "v2"
    v2.mkdir()
    (v2 / ".claude-plugin").mkdir()
    (v2 / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "2.0.0"}), encoding="utf-8"
    )
    (v2 / "marker.txt").write_text("two", encoding="utf-8")
    digest2, store2 = publish_source_tree(v2)
    from deepseek_tui.plugins.host import RollbackPlugin
    from deepseek_tui.plugins.store import link_or_copy_from_store

    link_or_copy_from_store(store2, plugins / "demo")
    assert (plugins / "demo" / "marker.txt").read_text(encoding="utf-8") == "two"
    result = PluginHost().apply(
        RollbackPlugin("demo", digest1, plugins_dir=plugins)
    )
    assert result.outcome == "rolled_back"
    assert (plugins / "demo" / "marker.txt").read_text(encoding="utf-8") == "one"
    assert digest2  # keep both digests in store


@pytest.mark.parametrize("bad_name", ["..", "../escape", "a/b", ".", "foo\\bar"])
def test_rollback_rejects_unsafe_plugin_names(
    tmp_path: Path, monkeypatch, bad_name: str
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "secret").write_text("keep", encoding="utf-8")
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "marker.txt").write_text("x", encoding="utf-8")
    digest, _ = publish_source_tree(src)
    from deepseek_tui.plugins.host import RollbackPlugin
    from deepseek_tui.plugins.store import rollback_plugin_link

    with pytest.raises(ValueError, match="invalid plugin name"):
        rollback_plugin_link(plugins, bad_name, digest)
    result = PluginHost().apply(RollbackPlugin(bad_name, digest, plugins_dir=plugins))
    assert result.outcome == "failed"
    assert victim.is_dir()
    assert (victim / "secret").read_text(encoding="utf-8") == "keep"
