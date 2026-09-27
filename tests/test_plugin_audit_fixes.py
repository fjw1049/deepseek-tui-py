"""Regression cases for audit 11. All sources/grants are temporary and offline."""

import json
from pathlib import Path

import pytest

from deepseek_tui.integrations import plugins, skills
from deepseek_tui.plugins.grants import grant_execution, read_grant, revoke_grant
from deepseek_tui.plugins.identity import source_content_digest
from deepseek_tui.plugins.source import LocalArtifact, PluginSourceError
from deepseek_tui.plugins.store import publish_source_tree


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))


def loaded(root: Path, *, scope="user"):
    root.mkdir(parents=True, exist_ok=True)
    return plugins.LoadedPlugin(
        manifest=plugins.PluginManifest(
            name="fixture",
            hooks=({"event": "session_start", "command": "not-executed"},),
            mcp_servers={"servers": {"fixture": {"command": "not-executed"}}},
        ),
        path=root,
        scope=scope,
        enabled=True,
        trusted=True,
    )


def test_digest_frames_paths_and_content(tmp_path):
    a, b = tmp_path / "one", tmp_path / "two"
    a.mkdir()
    b.mkdir()
    (a / "a").write_text("bc")
    (b / "ab").write_text("c")
    assert LocalArtifact(a).digest != LocalArtifact(b).digest


def test_provenance_cannot_choose_authorization_digest(tmp_path):
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "file").write_text("actual")
    assert (
        source_content_digest(root, provenance={"source": {"digest": "sha256:forged"}})
        == LocalArtifact(root).digest
    )


def test_store_hit_checks_actual_bytes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "file").write_text("original")
    _, stored = publish_source_tree(source)
    (stored / "file").write_text("corrupted")
    with pytest.raises(PluginSourceError):
        publish_source_tree(source)


def test_forged_store_path_does_not_inherit_grant(tmp_path):
    original = loaded(tmp_path / "original")
    digest = LocalArtifact(original.path).digest
    grant_execution("fixture", digest)
    forged = tmp_path / "outside" / "sources" / "sha256" / digest[7:]
    forged.mkdir(parents=True)
    (forged / "changed").write_text("different")
    link = tmp_path / "linked"
    link.symlink_to(forged, target_is_directory=True)
    candidate = loaded(link, scope="project")
    assert not plugins._project_trust_from_grants(
        "fixture", link, {"derived_provenance": {"source": {"digest": digest}}}
    )
    assert not plugins.collect_light_contributions([candidate]).hook_entries


@pytest.mark.parametrize(
    "caps,expected",
    [
        (frozenset(), (0, 0)),
        (frozenset({"hooks.execute"}), (1, 0)),
        (frozenset({"mcp.connect"}), (0, 1)),
        (frozenset({"hooks.execute", "mcp.connect"}), (1, 1)),
    ],
)
def test_capabilities_are_independent(tmp_path, caps, expected):
    plugin = loaded(tmp_path / "plugin")
    grant_execution("fixture", LocalArtifact(plugin.path).digest, capabilities=caps)
    contributions = plugins.collect_light_contributions([plugin])
    assert (len(contributions.hook_entries), len(contributions.mcp_servers)) == expected


def test_revoke_is_not_healed_by_loading(tmp_path):
    plugin = loaded(tmp_path / "plugin")
    digest = LocalArtifact(plugin.path).digest
    grant_execution("fixture", digest)
    revoke_grant("fixture")
    assert not plugins.collect_light_contributions([plugin]).hook_entries
    assert read_grant("fixture", digest) is None


def test_skill_failed_update_preserves_install(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("original")
    target = tmp_path / "skills"
    skills.install(skills.InstallSource.parse(str(source)), target, "demo")
    (target / "demo" / skills.INSTALLED_FROM_MARKER).write_text(
        json.dumps({"spec": "github:fixture/repo"})
    )

    def fail(*args, **kwargs):
        raise skills.GithubFetchError("offline failure")

    monkeypatch.setattr(skills, "fetch_github_archive", fail)
    outcome, _ = skills.update("demo", target)
    assert outcome == skills.InstallOutcome.FAILED
    assert (target / "demo" / "SKILL.md").read_text() == "original"


def test_skill_local_source_roundtrip(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("old")
    target = tmp_path / "skills"
    skills.install(skills.InstallSource.parse(str(source)), target, "demo")
    (source / "SKILL.md").write_text("new")
    monkeypatch.chdir(tmp_path.parent)
    assert skills.update("demo", target)[0] == skills.InstallOutcome.UPDATED
    assert (target / "demo" / "SKILL.md").read_text() == "new"


@pytest.mark.parametrize("name", ["../outside", "/outside", "nested/name", "..", r"..\outside"])
def test_skill_install_rejects_unsafe_name(tmp_path, name):
    if name == "/outside":
        name = str(tmp_path / "outside")
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("fixture")
    assert (
        skills.install(skills.InstallSource.parse(str(source)), tmp_path / "skills", name)[0]
        == skills.InstallOutcome.FAILED
    )


@pytest.mark.parametrize("operation", ["uninstall", "update", "trust"])
def test_skill_management_cannot_follow_escape(tmp_path, operation):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("preserve")
    (outside / skills.INSTALLED_FROM_MARKER).write_text('{"spec":"github:fixture/repo"}')
    target = tmp_path / "skills"
    target.mkdir()
    (target / "linked").symlink_to(outside, target_is_directory=True)
    for name in ("../outside", "linked"):
        getattr(skills, operation)(name, target)
    assert (outside / "SKILL.md").read_text() == "preserve"
    assert not (outside / skills.TRUSTED_MARKER).exists()


def test_skill_swap_failure_restores_original(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("old")
    target = tmp_path / "skills"
    skills.install(skills.InstallSource.parse(str(source)), target, "demo")
    (source / "SKILL.md").write_text("new")
    original = skills.os.replace

    def fail_second(src, dst):
        if Path(dst) == target / "demo" and Path(src).name == "demo":
            raise OSError("injected publish failure")
        return original(src, dst)

    monkeypatch.setattr(skills.os, "replace", fail_second)
    assert skills.update("demo", target)[0] == skills.InstallOutcome.FAILED
    assert (target / "demo" / "SKILL.md").read_text() == "old"


def test_session_light_reload_checks_revocation(tmp_path):
    from deepseek_tui.plugins.host import PluginSession, PluginStartup

    plugin = loaded(tmp_path / "plugin")
    digest = LocalArtifact(plugin.path).digest
    grant_execution("fixture", digest)
    session = PluginSession(workspace=tmp_path, loaded_plugins=[plugin], startup=PluginStartup())
    assert session.light_contributions("fixture").hook_entries
    revoke_grant("fixture")
    assert not session.light_contributions("fixture").hook_entries


def test_nested_resources_match_inspection_and_runtime(tmp_path):
    from deepseek_tui.plugins.adapters import inspect_local_source

    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "fixture"}))
    for folder, filename in [
        ("commands", "hello.md"),
        ("agents", "agent.md"),
        ("rules", "rule.md"),
        ("skills", "SKILL.md"),
    ]:
        dest = root / folder / "nested" / filename
        dest.parent.mkdir(parents=True)
        dest.write_text("---\nname: friendly\ndescription: fixture\n---\ncontent")
    packages, _ = inspect_local_source(root)
    inspected = {c.resources[0].path for c in packages[0].contributions if c.resources}
    manifest = plugins.load_plugin_manifest(root)
    candidate = plugins.LoadedPlugin(
        manifest=manifest, path=root, scope="user", enabled=True, trusted=False
    )
    actual = plugins.collect_contributions([candidate])
    paths = {
        x.path.relative_to(root).as_posix()
        for x in [*actual.commands, *actual.agents, *actual.rules, *actual.skills]
    }
    assert inspected == paths


async def test_composite_conflicts_are_not_published_or_called():
    from unittest.mock import AsyncMock
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.mcp.manager import McpManager
    from deepseek_tui.mcp.client import McpError
    from deepseek_tui.plugins.runtime import CompositeMcpManager

    managers = [McpManager([McpServerConfig(name="shared", command="unused")]) for _ in range(2)]
    schema = {"type": "function", "function": {"name": "mcp_shared_run"}}
    for manager in managers:
        manager.discover_tools = AsyncMock(return_value=[schema])
        manager.call_tool = AsyncMock()
    composite = CompositeMcpManager(*managers)
    assert await composite.discover_tools() == []
    with pytest.raises(McpError, match="ambiguous"):
        await composite.call_tool("mcp_shared_run", {})
    assert all(m.call_tool.await_count == 0 for m in managers)
    managers[1]._configs.clear()
    managers[1].discover_tools.return_value = []
    assert await composite.discover_tools() == [schema]
    await composite.call_tool("mcp_shared_run", {})
    managers[0].call_tool.assert_awaited_once()


def test_npm_body_stops_at_limit_and_rejects_redirect():
    import httpx
    from deepseek_tui.plugins.fetch import _bounded_get, RemoteFetchError

    consumed = []

    class Endless(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(100):
                consumed.append(i)
                yield b"x" * 65536

    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Endless()))
    ) as client:
        with pytest.raises(RemoteFetchError, match="exceeds"):
            _bounded_get(client, "https://registry.npmjs.org/test", 70000)
    assert len(consumed) == 2
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "https://outside.invalid"})
        )
    ) as client:
        with pytest.raises(RemoteFetchError, match="redirect"):
            _bounded_get(client, "https://registry.npmjs.org/test", 70000)


def test_skill_redirect_validated_before_request(monkeypatch):
    import httpx

    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://outside.invalid"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(skills.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(ValueError, match="not allowed"):
        skills._stream_download("https://github.com/fixture/repo", 100)
    assert len(calls) == 1


def test_plugin_archive_member_cap_precedes_full_scan(tmp_path):
    import io
    import tarfile
    from deepseek_tui.plugins.fetch import _extract_archive, RemoteFetchError

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for index in range(3):
            archive.addfile(tarfile.TarInfo(f"root/{index}"), io.BytesIO())
    with pytest.raises(RemoteFetchError, match="members"):
        _extract_archive(buffer.getvalue(), tmp_path / "dest", max_files=2, max_bytes=100)


def test_skill_update_drops_source_trust_marker(tmp_path):
    source, target = tmp_path / "source", tmp_path / "skills"
    source.mkdir()
    (source / "SKILL.md").write_text("# Fixture")
    skills.install(skills.InstallSource.parse(str(source)), target, "demo")
    (source / skills.TRUSTED_MARKER).touch()
    assert skills.update("demo", target)[0] == skills.InstallOutcome.UPDATED
    assert not (target / "demo" / skills.TRUSTED_MARKER).exists()


def test_skill_install_rejects_destination_inside_source(tmp_path):
    (tmp_path / "SKILL.md").write_text("# Fixture")
    assert skills.install(
        skills.InstallSource.parse(str(tmp_path)), tmp_path / "nested", "demo"
    )[0] == skills.InstallOutcome.FAILED
