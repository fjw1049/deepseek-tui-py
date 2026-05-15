"""Skills CLI + install hardening tests (HANDOVER §skills.2026-05-14).

Covers:

* CLI: ``cmd_skill`` install/update/uninstall/trust dispatch + read.
* CLI: ``cmd_skills`` ``--remote`` / ``sync`` / ``<prefix>`` paths.
* Install hardening (audit K-1..K-7):
    - K-1: cumulative decompressed-size cap (gzip-bomb defuse).
    - K-2: GitHub host allow-list.
    - K-3: path-traversal rejected (``../`` in tar member).
    - K-4: symlinks skipped + logged, never extracted.
    - K-5: top-level prefix detection robust to single-file roots.
    - K-7: SKILL.md accepted at root OR one nested dir.

Real network is never touched — extraction is exercised through the
``install_from_bytes`` test seam.
"""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deepseek_tui.skills import SKILL_FILENAME
from deepseek_tui.skills.install import (
    GITHUB_ALLOWED_HOSTS,
    REGISTRY_ALLOWED_HOSTS,
    InstallOutcome,
    InstallSource,
    _github_archive_urls,
    _host_is_allowed,
    _strip_prefix,
    install_from_bytes,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _make_tarball(entries: dict[str, bytes]) -> bytes:
    """Build a tar.gz archive in memory.

    Keys are tar member names (forward-slash separated, top-level prefix
    optional). Values are byte payloads. Directory entries are auto-added
    when needed.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # Sort to keep test output deterministic.
        for name in sorted(entries):
            data = entries[name]
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_tarball_with_symlink(name: str, target: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=name)
        info.type = tarfile.SYMTYPE
        info.linkname = target
        tf.addfile(info)
        # Also add a real SKILL.md so the rest of the pipeline succeeds.
        skill_data = b"---\nname: ok\ndescription: ok\n---\nbody\n"
        skill_info = tarfile.TarInfo(name="prefix/SKILL.md")
        skill_info.size = len(skill_data)
        tf.addfile(skill_info, io.BytesIO(skill_data))
    return buf.getvalue()


# ── K-2 + K-5: pure helpers ────────────────────────────────────────────


def test_host_allow_list_accepts_github() -> None:
    assert _host_is_allowed("https://github.com/a/b/archive.tar.gz", GITHUB_ALLOWED_HOSTS)
    assert _host_is_allowed("https://www.github.com/a/b/archive.tar.gz", GITHUB_ALLOWED_HOSTS)


def test_host_allow_list_rejects_other() -> None:
    assert not _host_is_allowed(
        "https://evil.example/foo.tar.gz", GITHUB_ALLOWED_HOSTS
    )
    # Hostname spoof attempt — the actual host is "evil.example".
    assert not _host_is_allowed(
        "https://evil.example/github.com/foo.tar.gz", GITHUB_ALLOWED_HOSTS
    )


def test_host_allow_list_rejects_non_https() -> None:
    assert not _host_is_allowed("ftp://github.com/x.tgz", GITHUB_ALLOWED_HOSTS)


def test_github_archive_urls_main_then_master() -> None:
    src = InstallSource(kind="github", owner="o", repo="r")
    urls = _github_archive_urls(src)
    assert urls == [
        "https://github.com/o/r/archive/refs/heads/main.tar.gz",
        "https://github.com/o/r/archive/refs/heads/master.tar.gz",
    ]


def test_strip_prefix_handles_edge_cases() -> None:
    assert _strip_prefix("prefix/foo.txt", "prefix") == "foo.txt"
    assert _strip_prefix("prefix", "prefix") == ""  # the dir entry itself
    assert _strip_prefix("other/foo", "prefix") == "other/foo"  # no match → keep
    assert _strip_prefix("prefixdir/foo", "prefix") == "prefixdir/foo"  # not a /-boundary


# ── K-1: gzip-bomb cap ─────────────────────────────────────────────────


def test_install_rejects_oversized_decompressed(tmp_path: Path) -> None:
    """A tarball whose contents exceed the cap must be rejected."""
    skills_dir = tmp_path / "skills"
    huge = b"A" * 200_000  # 200 KB — well over our 10 KB test cap.
    archive = _make_tarball(
        {
            "prefix/SKILL.md": b"---\nname: x\n---\nbody\n",
            "prefix/big.bin": huge,
        }
    )
    outcome, msg = install_from_bytes(
        archive,
        spec="github:o/r",
        skills_dir=skills_dir,
        name="x",
        max_size_bytes=10_000,
    )
    assert outcome == InstallOutcome.FAILED
    assert "decompressed" in msg.lower() or "exceed" in msg.lower() or "10000" in msg
    # And the partial directory must be cleaned up.
    assert not (skills_dir / "x").exists()


# ── K-3: path traversal ────────────────────────────────────────────────


def test_install_rejects_path_traversal(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    archive = _make_tarball(
        {
            "prefix/SKILL.md": b"---\nname: x\n---\n",
            "prefix/../../escape.txt": b"escape!",
        }
    )
    outcome, msg = install_from_bytes(
        archive, spec="github:o/r", skills_dir=skills_dir, name="x"
    )
    assert outcome == InstallOutcome.FAILED
    assert "traversal" in msg.lower() or "extract" in msg.lower()
    # Crucially, the escape file must not appear anywhere outside dest.
    assert not (tmp_path / "escape.txt").exists()
    assert not (skills_dir / "x").exists()


# ── K-4: symlinks ──────────────────────────────────────────────────────


def test_install_skips_symlinks(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    archive = _make_tarball_with_symlink("prefix/evil", "/etc/passwd")
    outcome, _msg = install_from_bytes(
        archive, spec="github:o/r", skills_dir=skills_dir, name="x"
    )
    assert outcome == InstallOutcome.INSTALLED
    # The symlink must not exist on disk; only the regular SKILL.md should.
    assert (skills_dir / "x" / SKILL_FILENAME).exists()
    assert not (skills_dir / "x" / "evil").exists()


# ── K-5: prefix detection ──────────────────────────────────────────────


def test_install_handles_archive_without_top_prefix(tmp_path: Path) -> None:
    """Archive whose first member is a *file* at the root.

    The old ``split('/', 1)[0]`` would pick the filename as the prefix
    and silently drop everything else. New code uses ``Path.parts[0]``
    AND tolerates an empty prefix.
    """
    skills_dir = tmp_path / "skills"
    # First member is a plain file — no leading directory.
    archive = _make_tarball(
        {
            "SKILL.md": b"---\nname: y\n---\nbody\n",
            "extra.txt": b"data",
        }
    )
    outcome, _msg = install_from_bytes(
        archive, spec="github:o/r", skills_dir=skills_dir, name="y"
    )
    assert outcome == InstallOutcome.INSTALLED
    assert (skills_dir / "y" / SKILL_FILENAME).is_file()


# ── K-7: nested layout ─────────────────────────────────────────────────


def test_install_accepts_nested_skill_md(tmp_path: Path) -> None:
    """SKILL.md sitting one level deeper (single subdir) is acceptable."""
    skills_dir = tmp_path / "skills"
    archive = _make_tarball(
        {
            "prefix/inner/SKILL.md": b"---\nname: z\n---\n",
            "prefix/inner/notes.md": b"# notes\n",
        }
    )
    outcome, _msg = install_from_bytes(
        archive, spec="github:o/r", skills_dir=skills_dir, name="z"
    )
    assert outcome == InstallOutcome.INSTALLED
    # Either layout (root or nested) must satisfy the validator.
    assert (skills_dir / "z" / "inner" / SKILL_FILENAME).is_file()


# ── fetch_registry host allow-list ─────────────────────────────────────


def test_fetch_registry_rejects_unknown_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepseek_tui.skills import install as install_mod

    called: list[str] = []

    class _BoomClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            called.append("constructed")

        def __enter__(self) -> _BoomClient:
            return self

        def __exit__(self, *a: Any) -> None:
            pass

        def get(self, url: str) -> Any:  # pragma: no cover — unreachable
            called.append(f"GET {url}")
            raise AssertionError("network must not be used")

    monkeypatch.setattr(install_mod.httpx, "Client", _BoomClient)

    result = install_mod.fetch_registry("https://evil.example/index.json")
    assert result is None
    assert called == []  # client must never have been constructed


def test_fetch_registry_allowed_hosts_set_is_sane() -> None:
    """At least the documented hosts must be in the allow-list."""
    assert "raw.githubusercontent.com" in REGISTRY_ALLOWED_HOSTS


# ── /skills CLI ────────────────────────────────────────────────────────


def _stub_app() -> Any:
    return SimpleNamespace(config=SimpleNamespace())


def test_cmd_skills_lists_local_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default ``/skills`` lists subdirs containing SKILL.md."""
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    skills_dir = tmp_path / "skills"
    (skills_dir / "alpha").mkdir(parents=True)
    (skills_dir / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n")
    (skills_dir / "beta").mkdir(parents=True)
    (skills_dir / "beta" / "SKILL.md").write_text("---\nname: beta\n---\n")

    monkeypatch.setattr(
        "deepseek_tui.skills.default_skills_dir", lambda: skills_dir
    )
    from deepseek_tui.tui.commands.handlers import cmd_skills

    result = cmd_skills("", _stub_app())
    assert not result.error
    assert "alpha" in (result.output or "")
    assert "beta" in (result.output or "")


def test_cmd_skills_filters_by_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_dir = tmp_path / "skills"
    for n in ("alpha", "beta", "alpine"):
        (skills_dir / n).mkdir(parents=True)
        (skills_dir / n / "SKILL.md").write_text("---\nname: " + n + "\n---\n")

    monkeypatch.setattr(
        "deepseek_tui.skills.default_skills_dir", lambda: skills_dir
    )
    from deepseek_tui.tui.commands.handlers import cmd_skills

    result = cmd_skills("alp", _stub_app())
    out = result.output or ""
    assert "alpha" in out
    assert "alpine" in out
    assert "beta" not in out


def test_cmd_skills_rejects_flag_like_prefix() -> None:
    from deepseek_tui.tui.commands.handlers import cmd_skills

    result = cmd_skills("--bogus", _stub_app())
    assert result.error


def test_cmd_skills_remote_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/skills --remote`` calls ``fetch_registry`` and renders entries."""
    from deepseek_tui.skills.install import RegistryDocument, RegistryEntry

    fake_doc = RegistryDocument(
        skills={
            "demo": RegistryEntry(source="github:o/demo", description="A demo skill"),
        }
    )
    monkeypatch.setattr(
        "deepseek_tui.tui.commands.handlers.fetch_registry"
        if False
        else "deepseek_tui.skills.install.fetch_registry",
        lambda url=None: fake_doc,
    )
    from deepseek_tui.tui.commands.handlers import cmd_skills

    result = cmd_skills("--remote", _stub_app())
    assert not result.error
    assert "demo" in (result.output or "")
    assert "A demo skill" in (result.output or "")


def test_cmd_skills_remote_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "deepseek_tui.skills.install.fetch_registry", lambda url=None: None
    )
    from deepseek_tui.tui.commands.handlers import cmd_skills

    result = cmd_skills("remote", _stub_app())
    assert result.error


# ── /skill CLI subcommands ──────────────────────────────────────────────


def test_cmd_skill_usage_when_empty() -> None:
    from deepseek_tui.tui.commands.handlers import cmd_skill

    result = cmd_skill("", _stub_app())
    assert result.error
    # All four subcommand names must appear in the help text so a user
    # who typed ``/skill`` blind learns what to type next.
    for sub in ("install", "update", "uninstall", "trust"):
        assert sub in (result.error or "")


def test_cmd_skill_install_invalid_spec() -> None:
    from deepseek_tui.tui.commands.handlers import cmd_skill

    result = cmd_skill("install not-a-real-spec", _stub_app())
    assert result.error
    assert "Invalid source" in (result.error or "")


def test_cmd_skill_install_dispatches_to_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(
        "deepseek_tui.skills.default_skills_dir", lambda: skills_dir
    )
    captured: list[Any] = []

    def fake_install(source: Any, skills_dir: Any = None) -> Any:
        captured.append((source, skills_dir))
        return (InstallOutcome.INSTALLED, "ok")

    monkeypatch.setattr(
        "deepseek_tui.skills.install.install", fake_install
    )
    from deepseek_tui.tui.commands.handlers import cmd_skill

    result = cmd_skill("install github:o/r", _stub_app())
    assert not result.error
    assert result.output == "ok"
    assert len(captured) == 1
    src, _dir = captured[0]
    assert src.kind == "github"
    assert src.owner == "o"
    assert src.repo == "r"


def test_cmd_skill_uninstall_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(
        "deepseek_tui.skills.default_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(
        "deepseek_tui.skills.install.uninstall",
        lambda name, skills_dir=None: f"Uninstalled {name}",
    )
    from deepseek_tui.tui.commands.handlers import cmd_skill

    result = cmd_skill("uninstall foo", _stub_app())
    assert not result.error
    assert "Uninstalled foo" in (result.output or "")


def test_cmd_skill_trust_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(
        "deepseek_tui.skills.default_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(
        "deepseek_tui.skills.install.trust",
        lambda name, skills_dir=None: f"Trusted {name}",
    )
    from deepseek_tui.tui.commands.handlers import cmd_skill

    result = cmd_skill("trust foo", _stub_app())
    assert not result.error
    assert "Trusted foo" in (result.output or "")


def test_cmd_skill_read_unknown_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(
        "deepseek_tui.skills.default_skills_dir", lambda: skills_dir
    )
    from deepseek_tui.tui.commands.handlers import cmd_skill

    result = cmd_skill("does-not-exist", _stub_app())
    assert result.error


def test_cmd_skill_read_returns_skill_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "demo").mkdir(parents=True)
    body = "---\nname: demo\n---\nHello world\n"
    (skills_dir / "demo" / "SKILL.md").write_text(body)
    monkeypatch.setattr(
        "deepseek_tui.skills.default_skills_dir", lambda: skills_dir
    )
    from deepseek_tui.tui.commands.handlers import cmd_skill

    result = cmd_skill("demo", _stub_app())
    assert not result.error
    assert "Hello world" in (result.output or "")


# ── Startup install_system_skills wiring ────────────────────────────────


def test_install_system_skills_idempotent(tmp_path: Path) -> None:
    """Calling twice must not error and must leave the bundled skill in place."""
    from deepseek_tui.skills.system import (
        SKILL_CREATOR_BODY,  # noqa: F401 — sanity import
        SYSTEM_SKILL_VERSION,
        install_system_skills,
    )

    install_system_skills(tmp_path)
    install_system_skills(tmp_path)  # second call should be a no-op
    creator = tmp_path / "skill-creator"
    assert (creator / SKILL_FILENAME).is_file()
    assert (creator / ".system-installed-version").read_text().strip() == SYSTEM_SKILL_VERSION


# ── Round-trip: install_from_bytes leaves a valid registry entry ────────


def test_install_from_bytes_writes_marker(tmp_path: Path) -> None:
    """The ``.installed-from`` marker must be a valid JSON dict with the spec."""
    skills_dir = tmp_path / "skills"
    archive = _make_tarball(
        {"prefix/SKILL.md": b"---\nname: m\n---\n"}
    )
    outcome, _ = install_from_bytes(
        archive, spec="github:o/r", skills_dir=skills_dir, name="m"
    )
    assert outcome == InstallOutcome.INSTALLED
    marker = skills_dir / "m" / ".installed-from"
    assert marker.is_file()
    payload = json.loads(marker.read_text())
    assert payload["spec"] == "github:o/r"
