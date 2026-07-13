from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from deepseek_tui.plugins import InstallPlugin, PluginHost, UpdatePlugin
from deepseek_tui.plugins.fetch import (
    GitSubdirSource,
    RemoteFetchError,
    materialize_git_subdir,
)


def _archive(
    files: dict[str, str],
    *,
    symlink: tuple[str, str] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in files.items():
            payload = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if symlink is not None:
            info = tarfile.TarInfo(symlink[0])
            info.type = tarfile.SYMTYPE
            info.linkname = symlink[1]
            archive.addfile(info)
    return buffer.getvalue()


def _remote_marketplace(root: Path) -> None:
    marker = root / ".claude-plugin"
    marker.mkdir(parents=True)
    (marker / "marketplace.json").write_text(
        json.dumps(
            {
                "plugins": [
                    {
                        "name": "remote-demo",
                        "version": "1.0.0",
                        "source": {
                            "source": "git-subdir",
                            "url": "https://github.com/example/remote-repo.git",
                            "path": "plugins/demo",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _remote_plugin_archive(version: str) -> bytes:
    return _archive(
        {
            "remote-repo-main/plugins/demo/.claude-plugin/plugin.json": json.dumps(
                {"name": "remote-demo", "version": version, "skills": "./skills"}
            ),
            "remote-repo-main/plugins/demo/skills/demo/SKILL.md": (
                "---\nname: remote-skill\ndescription: Remote.\n---\nBody.\n"
            ),
        }
    )


def test_git_subdir_source_is_strict_and_builds_codeload_urls() -> None:
    source = GitSubdirSource.parse(
        "https://github.com/example/demo.git",
        "plugins/alpha",
    )

    assert source.install_spec == "github:example/demo#plugins/alpha"
    assert source.archive_candidates() == (
        (
            "main",
            "https://codeload.github.com/example/demo/tar.gz/refs/heads/main",
        ),
        (
            "master",
            "https://codeload.github.com/example/demo/tar.gz/refs/heads/master",
        ),
    )


@pytest.mark.parametrize(
    ("url", "subdir"),
    [
        ("http://github.com/example/demo", "plugin"),
        ("https://evil.example/example/demo", "plugin"),
        ("https://github.com/example/demo/extra", "plugin"),
        ("https://github.com/example/demo?ref=x", "plugin"),
        ("https://github.com/example/demo", "../plugin"),
        ("https://github.com/example/demo", "/plugin"),
        ("https://github.com/example/demo", r"nested\plugin"),
    ],
)
def test_git_subdir_source_rejects_unsafe_values(url: str, subdir: str) -> None:
    with pytest.raises(RemoteFetchError):
        GitSubdirSource.parse(url, subdir)


def test_materialize_git_subdir_extracts_safely_and_cleans_up(
    tmp_path: Path, monkeypatch
) -> None:
    source = GitSubdirSource.parse(
        "https://github.com/example/demo.git", "plugins/alpha"
    )
    data = _archive(
        {"demo-main/plugins/alpha/.claude-plugin/plugin.json": '{"name":"alpha"}'}
    )
    monkeypatch.setattr(
        "deepseek_tui.plugins.fetch._download_archive",
        lambda url, max_bytes: data,
    )

    with materialize_git_subdir(source, temp_parent=tmp_path) as resolved:
        package_path = resolved.path
        assert (package_path / ".claude-plugin" / "plugin.json").is_file()
        assert resolved.ref == "main"
        assert resolved.digest.startswith("sha256:")
    assert not package_path.exists()


def test_materialize_git_subdir_rejects_archive_links(
    tmp_path: Path, monkeypatch
) -> None:
    source = GitSubdirSource.parse("https://github.com/example/demo", ".")
    data = _archive(
        {"demo-main/package.json": "{}"},
        symlink=("demo-main/escape", "../../outside"),
    )
    monkeypatch.setattr(
        "deepseek_tui.plugins.fetch._download_archive",
        lambda url, max_bytes: data,
    )

    with pytest.raises(RemoteFetchError, match="link|special"):
        with materialize_git_subdir(source, temp_parent=tmp_path):
            pass
    assert list(tmp_path.iterdir()) == []


def test_host_installs_and_updates_selected_remote_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    marketplace = tmp_path / "marketplace"
    installed = tmp_path / "installed"
    _remote_marketplace(marketplace)
    archive = [_remote_plugin_archive("1.0.0")]
    monkeypatch.setattr(
        "deepseek_tui.plugins.fetch._download_archive",
        lambda url, max_bytes: archive[0],
    )
    host = PluginHost()

    result = host.apply(
        InstallPlugin(
            source=str(marketplace),
            plugin_id="remote-demo",
            plugins_dir=installed,
        )
    )

    assert result.outcome == "installed"
    lock_path = installed / "installed_plugins.json"
    entry = json.loads(lock_path.read_text(encoding="utf-8"))["plugins"][
        "remote-demo"
    ]
    assert entry["source"] == "github:example/remote-repo#plugins/demo"
    provenance = entry["derived_provenance"]
    assert provenance["source"]["kind"] == "git-subdir"
    assert provenance["source"]["relative_root"] == "plugins/demo"
    assert provenance["source"]["digest"].startswith("sha256:")
    assert provenance["resolved"]["ref"] == "main"
    assert provenance["catalog"]["locator"] == str(marketplace.resolve())
    first_digest = provenance["source"]["digest"]

    archive[0] = _remote_plugin_archive("2.0.0")
    updated = host.apply(UpdatePlugin("remote-demo", installed))

    assert updated.outcome == "updated"
    document = json.loads(
        (installed / "remote-demo" / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert document["version"] == "2.0.0"
    updated_entry = json.loads(lock_path.read_text(encoding="utf-8"))["plugins"][
        "remote-demo"
    ]
    assert updated_entry["derived_provenance"]["source"]["digest"] != first_digest
    assert updated_entry["derived_provenance"]["catalog"]["locator"] == str(
        marketplace.resolve()
    )


def test_host_rejects_remote_package_id_mismatch(tmp_path: Path, monkeypatch) -> None:
    marketplace = tmp_path / "marketplace"
    installed = tmp_path / "installed"
    _remote_marketplace(marketplace)
    mismatched = _archive(
        {
            "remote-repo-main/plugins/demo/.claude-plugin/plugin.json": json.dumps(
                {"name": "different-plugin", "version": "1.0.0"}
            )
        }
    )
    monkeypatch.setattr(
        "deepseek_tui.plugins.fetch._download_archive",
        lambda url, max_bytes: mismatched,
    )

    result = PluginHost().apply(
        InstallPlugin(
            source=str(marketplace),
            plugin_id="remote-demo",
            plugins_dir=installed,
        )
    )

    assert result.outcome == "failed"
    assert "id mismatch" in result.message
    assert not installed.exists() or not (installed / "different-plugin").exists()
