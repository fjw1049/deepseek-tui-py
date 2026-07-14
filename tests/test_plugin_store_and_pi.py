from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.plugins.host import InstallPlugin, PluginHost
from deepseek_tui.plugins.pi_runtime import PiNodeRuntime, PiProviderSpec
from deepseek_tui.plugins.store import publish_source_tree, source_path


def _write_pi_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "pi-echo",
                "version": "0.1.0",
                "description": "fixture",
                "pi": {"extensions": ["./ext.js"]},
            }
        ),
        encoding="utf-8",
    )
    (root / "ext.js").write_text(
        """
export default function (pi) {
  pi.registerTool({
    name: "echo",
    label: "Echo",
    description: "Echo text",
    parameters: {
      type: "object",
      properties: { text: { type: "string" } },
      required: ["text"],
    },
    async execute(_id, params) {
      return {
        content: [{ type: "text", text: String(params.text || "") }],
        details: { echoed: true },
      };
    },
  });
  pi.registerCommand("ping", {
    description: "Ping",
    handler: async () => {},
  });
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return root


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


@pytest.mark.asyncio
async def test_pi_sidecar_lists_and_calls_tool(tmp_path: Path) -> None:
    import shutil

    if shutil.which("node") is None:
        pytest.skip("node not available")
    package = _write_pi_fixture(tmp_path / "pi-echo")
    runtime = PiNodeRuntime(
        PiProviderSpec(
            plugin_id="pi-echo",
            package_root=str(package),
            entrypoints=("./ext.js",),
        )
    )
    try:
        await runtime.start()
        tools = await runtime.list_tools()
        assert [tool.name for tool in tools] == ["echo"]
        result = await runtime.call_tool("echo", {"text": "hi"})
        assert result["content"][0]["text"] == "hi"
        assert result["details"]["echoed"] is True
        commands = await runtime.list_commands()
        assert commands[0]["name"] == "ping"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_pi_host_activation_registers_tools(tmp_path: Path, monkeypatch) -> None:
    import shutil

    if shutil.which("node") is None:
        pytest.skip("node not available")
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    _write_pi_fixture(tmp_path / "home" / "plugins" / "pi-echo")
    from deepseek_tui.integrations.plugins import set_plugin_trusted
    from deepseek_tui.plugins import GrantPlugin, PluginHost
    from deepseek_tui.plugins.identity import source_content_digest
    from deepseek_tui.tools.registry import ToolRegistry

    plugins_dir = tmp_path / "home" / "plugins"
    set_plugin_trusted("pi-echo", True, plugins_dir)
    # Pi is a high-risk runtime.tool-provider: trust alone is not enough, the
    # user must deliberately grant execution for the current content digest.
    digest = source_content_digest(plugins_dir / "pi-echo")
    PluginHost().apply(GrantPlugin("pi-echo", digest, plugins_dir))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session = PluginHost().open_session(workspace=workspace)
    registry = ToolRegistry()
    tools = await session.activate_pi_provider("pi-echo", tool_registry=registry)
    assert len(tools) == 1
    assert any(name.startswith("pi_") for name in registry.names())
    await session.close()


@pytest.mark.asyncio
async def test_pi_trust_alone_does_not_activate(tmp_path: Path, monkeypatch) -> None:
    """Trust grants only low-risk caps; the Pi sidecar stays inert until a
    deliberate ``plugin grant`` authorizes ``runtime.tool-provider``."""
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    _write_pi_fixture(tmp_path / "home" / "plugins" / "pi-echo")
    from deepseek_tui.integrations.plugins import set_plugin_trusted
    from deepseek_tui.plugins import PluginHost
    from deepseek_tui.tools.registry import ToolRegistry

    set_plugin_trusted("pi-echo", True, tmp_path / "home" / "plugins")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session = PluginHost().open_session(workspace=workspace)
    registry = ToolRegistry()
    tools = await session.activate_pi_provider("pi-echo", tool_registry=registry)
    assert tools == []
    assert not any(name.startswith("pi_") for name in registry.names())
    await session.close()


def test_pi_adapter_allows_install_when_node_present(tmp_path: Path) -> None:
    from deepseek_tui.plugins.adapters import inspect_local_source

    package = _write_pi_fixture(tmp_path / "pkg")
    packages, _ = inspect_local_source(package)
    assert len(packages) == 1
    assert packages[0].compatibility.can_install is True


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


@pytest.mark.asyncio
async def test_pi_sidecar_loads_typescript_entrypoint(tmp_path: Path) -> None:
    import shutil

    from deepseek_tui.plugins.pi_runtime import node_supports_strip_types

    if shutil.which("node") is None or not node_supports_strip_types():
        pytest.skip("node strip-types unavailable")
    root = tmp_path / "pi-ts"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "pi-ts",
                "version": "0.1.0",
                "pi": {"extensions": ["./ext.ts"]},
            }
        ),
        encoding="utf-8",
    )
    (root / "ext.ts").write_text(
        """
type Args = { text: string };
export default function (pi: any) {
  pi.registerTool({
    name: "echo_ts",
    description: "Echo",
    parameters: {
      type: "object",
      properties: { text: { type: "string" } },
      required: ["text"],
    },
    async execute(_id: string, params: Args) {
      return { content: [{ type: "text", text: params.text }], details: {} };
    },
  });
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    from deepseek_tui.plugins.adapters import inspect_local_source

    packages, _ = inspect_local_source(root)
    assert packages[0].compatibility.can_activate is True
    codes = {d.code for d in packages[0].compatibility.diagnostics}
    assert "PI_TYPESCRIPT_STRIP_TYPES" in codes
    runtime = PiNodeRuntime(
        PiProviderSpec(
            plugin_id="pi-ts",
            package_root=str(root),
            entrypoints=("./ext.ts",),
        )
    )
    try:
        await runtime.start()
        tools = await runtime.list_tools()
        assert [tool.name for tool in tools] == ["echo_ts"]
        result = await runtime.call_tool("echo_ts", {"text": "ts"})
        assert result["content"][0]["text"] == "ts"
    finally:
        await runtime.shutdown()
