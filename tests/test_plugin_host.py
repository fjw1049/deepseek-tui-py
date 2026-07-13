from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from deepseek_tui.plugins import InstallPlugin, PluginHost, UpdatePlugin


def _make_plugin(
    root: Path,
    name: str,
    *,
    with_command: bool = False,
    with_agent: bool = False,
    with_mcp: bool = False,
) -> None:
    plugin = root / name
    manifest: dict[str, object] = {
        "name": name,
        "version": "1.2.3",
        "skills": "./skills",
    }
    skill = plugin / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo.\n---\nBody.\n",
        encoding="utf-8",
    )
    if with_command:
        commands = plugin / "commands"
        commands.mkdir()
        (commands / "greet.md").write_text(
            "---\ndescription: Greet.\n---\nHello.\n",
            encoding="utf-8",
        )
        manifest["commands"] = "./commands"
    if with_agent:
        agents = plugin / "agents"
        agents.mkdir()
        (agents / "specialist.md").write_text(
            "---\nname: demo-specialist\ndescription: Specialist.\n---\nFocus.\n",
            encoding="utf-8",
        )
        manifest["agents"] = "./agents"
    if with_mcp:
        manifest["mcpServers"] = {"tools": {"command": "cat", "args": []}}
    manifest_dir = plugin / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def test_plugin_host_opens_frozen_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    _make_plugin(
        plugins_dir,
        "demo",
        with_command=True,
        with_agent=True,
    )

    session = PluginHost().open_session(workspace=tmp_path / "workspace")
    _make_plugin(plugins_dir, "late")

    assert session.plugin("DEMO") is not None
    assert session.plugin("late") is None
    assert [skill.name for skill in session.startup.skills] == ["demo-skill"]
    activation = session.activate("demo")
    assert activation is not None
    assert [command.qualified for command in activation.commands] == ["demo:greet"]
    assert [agent.name for agent in activation.agents] == ["demo-specialist"]
    assert session.activate("demo") is activation


def test_plugin_host_inspect_returns_stable_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    _make_plugin(
        tmp_path / "home" / "plugins",
        "demo",
    )

    inspection = PluginHost().inspect(workspace=tmp_path / "workspace")

    assert [(item.name, item.version, item.scope) for item in inspection.plugins] == [
        ("demo", "1.2.3", "user")
    ]


def test_plugin_host_apply_delegates_lifecycle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    source_root = tmp_path / "source"
    _make_plugin(source_root, "demo")

    result = PluginHost().apply(InstallPlugin(source=str(source_root / "demo")))

    assert result.outcome == "installed"
    assert (tmp_path / "home" / "plugins" / "demo").is_dir()


def test_plugin_host_installs_selected_candidate_from_collection(tmp_path: Path) -> None:
    source = tmp_path / "collection"
    target = tmp_path / "installed"
    _make_plugin(source, "alpha")
    _make_plugin(source, "beta")

    result = PluginHost().apply(
        InstallPlugin(
            source=str(source),
            plugin_id="beta",
            plugins_dir=target,
        )
    )

    assert result.outcome == "installed"
    assert not (target / "alpha").exists()
    assert (target / "beta").is_dir()
    lock = json.loads((target / "installed_plugins.json").read_text(encoding="utf-8"))
    assert lock["plugins"]["beta"]["source"] == str((source / "beta").resolve())
    provenance = lock["plugins"]["beta"]["derived_provenance"]
    assert provenance["plugin_id"] == "beta"
    assert provenance["source"]["locator"] == str(source.resolve())
    assert provenance["source"]["relative_root"] == "beta"
    assert provenance["source"]["digest"].startswith("sha256:")
    assert provenance["adapter_id"] == "claude"


def test_plugin_host_requires_selector_for_collection(tmp_path: Path) -> None:
    source = tmp_path / "collection"
    _make_plugin(source, "alpha")
    _make_plugin(source, "beta")

    result = PluginHost().apply(InstallPlugin(source=str(source)))

    assert result.outcome == "failed"
    assert "multiple plugin candidates" in result.message
    assert "--plugin" in result.message


def test_plugin_host_requires_candidate_root_for_duplicate_id(tmp_path: Path) -> None:
    source = tmp_path / "collection"
    _make_plugin(source / "one", "duplicate")
    _make_plugin(source / "two", "duplicate")

    ambiguous = PluginHost().apply(
        InstallPlugin(source=str(source), plugin_id="duplicate")
    )
    selected = PluginHost().apply(
        InstallPlugin(
            source=str(source),
            plugin_id="duplicate",
            candidate_root="two/duplicate",
            plugins_dir=tmp_path / "installed",
        )
    )

    assert ambiguous.outcome == "failed"
    assert "candidate_root" in ambiguous.message
    assert selected.outcome == "installed"


def test_plugin_host_rejects_unknown_or_traversing_candidate_root(
    tmp_path: Path,
) -> None:
    source = tmp_path / "collection"
    target = tmp_path / "installed"
    _make_plugin(source, "alpha")

    result = PluginHost().apply(
        InstallPlugin(
            source=str(source),
            candidate_root="../alpha",
            plugins_dir=target,
        )
    )

    assert result.outcome == "failed"
    assert "No plugin candidate matched" in result.message
    assert not target.exists()


def test_plugin_host_rejects_blocked_pi_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "deepseek_tui.plugins.pi_runtime.node_supports_strip_types",
        lambda node_bin=None: False,
    )
    source = tmp_path / "src"
    source.mkdir()
    (source / "package.json").write_text(
        json.dumps(
            {
                "name": "pi-demo",
                "version": "1.0.0",
                "pi": {"extensions": ["./index.ts"]},
            }
        ),
        encoding="utf-8",
    )
    (source / "index.ts").write_text("export default {};", encoding="utf-8")

    result = PluginHost().apply(
        InstallPlugin(source=str(source), plugins_dir=tmp_path / "installed")
    )

    assert result.outcome == "failed"
    assert "activation is blocked" in result.message


def test_plugin_host_installs_typescript_pi_when_strip_types_available(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "deepseek_tui.plugins.pi_runtime.node_supports_strip_types",
        lambda node_bin=None: True,
    )
    source = tmp_path / "src"
    source.mkdir()
    (source / "package.json").write_text(
        json.dumps(
            {
                "name": "pi-demo-ts",
                "version": "1.0.0",
                "pi": {"extensions": ["./index.ts"]},
            }
        ),
        encoding="utf-8",
    )
    (source / "index.ts").write_text(
        "export default function (pi) { pi.registerTool({ name: 't', "
        "async execute() { return { content: [] }; } }); }\n",
        encoding="utf-8",
    )

    result = PluginHost().apply(
        InstallPlugin(source=str(source), plugins_dir=tmp_path / "installed")
    )

    assert result.outcome == "installed"
    assert (tmp_path / "installed" / "pi-demo-ts").exists()


def test_selected_collection_candidate_can_update_from_recorded_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "collection"
    target = tmp_path / "installed"
    _make_plugin(source, "alpha")
    _make_plugin(source, "beta")
    host = PluginHost()
    installed = host.apply(
        InstallPlugin(source=str(source), plugin_id="beta", plugins_dir=target)
    )
    assert installed.outcome == "installed"
    manifest = source / "beta" / ".claude-plugin" / "plugin.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["version"] = "2.0.0"
    manifest.write_text(json.dumps(document), encoding="utf-8")

    updated = host.apply(UpdatePlugin("beta", target))

    assert updated.outcome == "updated"
    installed_manifest = json.loads(
        (target / "beta" / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert installed_manifest["version"] == "2.0.0"
    updated_lock = json.loads(
        (target / "installed_plugins.json").read_text(encoding="utf-8")
    )
    assert updated_lock["plugins"]["beta"]["derived_provenance"]["plugin_id"] == (
        "beta"
    )


async def test_engine_uses_plugin_session_seam(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    _make_plugin(
        tmp_path / "home" / "plugins",
        "demo",
        with_command=True,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    engine = await Engine.create(
        EngineHandle(),
        AsyncMock(),
        config=Config(features={"tasks": False, "subagents": False, "mcp": False}),
        working_directory=workspace,
    )
    try:
        assert engine.plugin_session is not None
        assert engine.plugin_session.plugin("demo") is not None
        assert engine.ensure_plugin_activated("demo")
        assert "demo:greet" in engine.plugin_commands
    finally:
        await engine.shutdown_session()


async def test_shared_runtime_gets_session_scoped_plugin_mcp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    _make_plugin(plugins_dir, "demo", with_mcp=True)

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.integrations.plugins import set_plugin_trusted
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.tools.runtime import create_tool_runtime

    set_plugin_trusted("demo", True, plugins_dir)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = Config(
        features={"tasks": False, "subagents": False, "mcp": True},
        mcp_config_path=tmp_path / "mcp.json",
    )
    shared = await create_tool_runtime(
        config=cfg,
        working_directory=workspace,
        mcp_manager=None,
        extra_mcp_servers=[McpServerConfig(name="base", command="cat")],
    )
    engine = await Engine.create(
        EngineHandle(),
        AsyncMock(),
        config=cfg,
        working_directory=workspace,
        tool_runtime=shared,
    )
    try:
        assert set(engine.mcp_manager.server_names) == {"base", "demo-tools"}
        assert shared.mcp_manager is not None
        assert shared.mcp_manager.server_names == ["base"]
    finally:
        await engine.shutdown_session()
        await shared.shutdown()
