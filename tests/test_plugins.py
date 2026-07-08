"""Plugin system tests — manifest parsing, discovery, lockfile lifecycle,
contribution fan-out, and Engine.create integration."""

from __future__ import annotations

import json
from pathlib import Path

from deepseek_tui.integrations.plugins import (
    PluginRegistryDocument,
    capability_values_from_permissions,
    collect_contributions,
    discover_claude_plugins,
    discover_plugins,
    install_plugin,
    load_plugin_manifest,
    merge_plugin_skills,
    read_lockfile,
    set_plugin_enabled,
    set_plugin_trusted,
    uninstall_plugin,
)
from deepseek_tui.integrations.skills import InstallOutcome, SkillRegistry


def make_plugin(
    root: Path,
    name: str = "demo",
    *,
    manifest_dir: str = ".deepseek-plugin",
    with_skill: bool = True,
    with_hook: bool = True,
    with_mcp: bool = True,
    extra_manifest: dict | None = None,
) -> Path:
    plugin = root / name
    plugin.mkdir(parents=True)
    manifest: dict = {"name": name, "version": "1.2.3", "description": "demo plugin"}
    if with_skill:
        skills = plugin / "skills" / "demo-skill"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: A demo skill.\n---\n\nBody.\n",
            encoding="utf-8",
        )
        manifest["skills"] = "./skills"
    if with_hook:
        (plugin / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": [
                        {
                            "event": "session_start",
                            "command": "echo ${PLUGIN_DIR}/hi",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        manifest["hooks"] = ["./hooks.json"]
    if with_mcp:
        manifest["mcpServers"] = {
            "srv": {"command": "${PLUGIN_DIR}/bin/server", "args": ["--x"]}
        }
    if extra_manifest:
        manifest.update(extra_manifest)
    mdir = plugin / manifest_dir
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return plugin


# ── Manifest ─────────────────────────────────────────────────────────────


def test_manifest_parses_deepseek_location(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.name == "demo"
    assert manifest.version == "1.2.3"
    assert manifest.skills == ("./skills",)
    assert len(manifest.hooks) == 1
    assert manifest.mcp_servers


def test_manifest_claude_code_compat_location(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path, manifest_dir=".claude-plugin")
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.name == "demo"


def test_manifest_unsupported_components_flagged(tmp_path: Path) -> None:
    plugin = make_plugin(
        tmp_path, extra_manifest={"commands": "./commands", "agents": "./agents"}
    )
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert set(manifest.unsupported) == {"commands", "agents"}


def test_manifest_missing_returns_none(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert load_plugin_manifest(tmp_path / "empty") is None


# ── Discovery + lockfile ─────────────────────────────────────────────────


def test_discover_and_default_state(tmp_path: Path) -> None:
    make_plugin(tmp_path)
    plugins = discover_plugins(plugins_dir=tmp_path)
    assert len(plugins) == 1
    p = plugins[0]
    assert p.name == "demo"
    assert p.enabled and not p.trusted


def test_disable_hides_plugin(tmp_path: Path) -> None:
    make_plugin(tmp_path)
    set_plugin_enabled("demo", False, tmp_path)
    assert discover_plugins(plugins_dir=tmp_path) == []
    all_plugins = discover_plugins(plugins_dir=tmp_path, include_disabled=True)
    assert len(all_plugins) == 1 and not all_plugins[0].enabled
    set_plugin_enabled("demo", True, tmp_path)
    assert len(discover_plugins(plugins_dir=tmp_path)) == 1


def test_project_scope_wins_on_conflict(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    project_dir = workspace / ".deepseek" / "plugins"
    make_plugin(project_dir, "demo", extra_manifest={"version": "9.9.9"})
    user_dir = tmp_path / "user-plugins"
    make_plugin(user_dir, "demo")
    plugins = discover_plugins(workspace=workspace)
    demo = [p for p in plugins if p.name == "demo"]
    assert demo and demo[0].manifest.version == "9.9.9"
    assert demo[0].scope == "project"


# ── Contributions ────────────────────────────────────────────────────────


def test_untrusted_plugin_only_contributes_skills(tmp_path: Path) -> None:
    make_plugin(tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert [s.name for s in contribs.skills] == ["demo-skill"]
    assert contribs.hook_entries == []
    assert contribs.mcp_servers == []
    assert any("not trusted" in w for w in contribs.warnings)


def test_trusted_plugin_contributes_hooks_and_mcp(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    set_plugin_trusted("demo", True, tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert len(contribs.hook_entries) == 1
    hook = contribs.hook_entries[0]
    assert hook.event == "session_start"
    assert str(plugin) in hook.command  # ${PLUGIN_DIR} expanded
    assert hook.name == "demo:session_start"
    assert len(contribs.mcp_servers) == 1
    srv = contribs.mcp_servers[0]
    assert srv.name == "demo-srv"
    assert srv.command == f"{plugin}/bin/server"


def test_invalid_hook_event_skipped_with_warning(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path, with_hook=False, with_mcp=False)
    (plugin / "hooks.json").write_text(
        json.dumps({"hooks": [{"event": "bogus_event", "command": "echo hi"}]}),
        encoding="utf-8",
    )
    manifest_path = plugin / ".deepseek-plugin" / "plugin.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["hooks"] = ["./hooks.json"]
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    set_plugin_trusted("demo", True, tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert contribs.hook_entries == []
    assert any("invalid hook entry" in w for w in contribs.warnings)


def test_merge_plugin_skills_workspace_wins(tmp_path: Path) -> None:
    make_plugin(tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    registry = SkillRegistry()
    merge_plugin_skills(registry, contribs)
    assert registry.get("demo-skill") is not None
    # Re-merge is idempotent on names.
    merge_plugin_skills(registry, contribs)
    assert len([s for s in registry.skills if s.name == "demo-skill"]) == 1


# ── Install lifecycle ────────────────────────────────────────────────────


def test_install_local_records_lockfile(tmp_path: Path) -> None:
    src = make_plugin(tmp_path / "src")
    target = tmp_path / "installed"
    outcome, message = install_plugin(str(src), target)
    assert outcome == InstallOutcome.INSTALLED
    assert "stay inactive" in message  # trust warning for hooks/MCP
    entry = read_lockfile(target)["demo"]
    assert entry["source"] == f"local:{src}"
    assert entry["version"] == "1.2.3"
    assert entry["enabled"] is True and entry["trusted"] is False

    # Duplicate install refuses.
    outcome, _ = install_plugin(str(src), target)
    assert outcome == InstallOutcome.ALREADY_EXISTS


def test_install_with_trust_flag(tmp_path: Path) -> None:
    src = make_plugin(tmp_path / "src")
    target = tmp_path / "installed"
    outcome, _ = install_plugin(str(src), target, trust=True)
    assert outcome == InstallOutcome.INSTALLED
    assert read_lockfile(target)["demo"]["trusted"] is True


def test_install_rejects_dir_without_manifest(tmp_path: Path) -> None:
    src = tmp_path / "not-a-plugin"
    src.mkdir()
    outcome, message = install_plugin(str(src), tmp_path / "installed")
    assert outcome == InstallOutcome.FAILED
    assert "manifest" in message


def test_uninstall_removes_dir_and_lock_entry(tmp_path: Path) -> None:
    src = make_plugin(tmp_path / "src")
    target = tmp_path / "installed"
    install_plugin(str(src), target)
    message = uninstall_plugin("demo", target)
    assert "Uninstalled" in message
    assert not (target / "demo").exists()
    assert "demo" not in read_lockfile(target)
    assert uninstall_plugin("demo", target) == "Plugin not found: demo"


# ── Permissions → capabilities ───────────────────────────────────────────


def test_manifest_permissions_normalized(tmp_path: Path) -> None:
    plugin = make_plugin(
        tmp_path, extra_manifest={"permissions": ["Read", "NETWORK", " shell "]}
    )
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.permissions == ("read", "network", "shell")


def test_capability_mapping_and_unknown_dropped() -> None:
    caps = capability_values_from_permissions(("read", "network", "quantum"))
    assert caps == ["read_only", "network"]
    assert capability_values_from_permissions(()) == []


def test_mcp_approval_relaxed_by_declared_read_only() -> None:
    from deepseek_tui.tools.approval import (
        needs_mcp_approval_prompt,
        plan_requires_mcp_approval,
    )

    name = "mcp_demo-srv__do_thing"
    # Default: non-read-only MCP tool always requires approval.
    assert plan_requires_mcp_approval(name, "on-request") is True
    # Declared read-only plugin permission maps to AUTO.
    assert plan_requires_mcp_approval(name, "on-request", ["read_only"]) is False
    assert needs_mcp_approval_prompt(name, "on-request", ["read_only"]) is False
    # Declared executes_code stays REQUIRED.
    assert plan_requires_mcp_approval(name, "on-request", ["executes_code"]) is True
    # Unknown declared strings fall back to the conservative default.
    assert plan_requires_mcp_approval(name, "on-request", ["quantum"]) is True


def test_declared_permissions_flow_to_mcp_server_config(tmp_path: Path) -> None:
    make_plugin(tmp_path, extra_manifest={"permissions": ["read", "network"]})
    set_plugin_trusted("demo", True, tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    srv = contribs.mcp_servers[0]
    assert srv.capabilities == ["read_only", "network"]


# ── Lazy MCP startup ─────────────────────────────────────────────────────


def test_plugin_mcp_servers_default_lazy(tmp_path: Path) -> None:
    make_plugin(tmp_path)
    set_plugin_trusted("demo", True, tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert contribs.mcp_servers[0].lazy is True


def test_plugin_mcp_lazy_opt_out(tmp_path: Path) -> None:
    make_plugin(
        tmp_path,
        extra_manifest={
            "mcpServers": {"srv": {"command": "cat", "lazy": False}}
        },
    )
    set_plugin_trusted("demo", True, tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert contribs.mcp_servers[0].lazy is False


async def test_start_all_skips_lazy_servers() -> None:
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.mcp.manager import McpManager

    manager = McpManager(
        [
            # Both would fail to connect if started; the lazy one must not
            # even be attempted so it can't appear in ready/failed.
            McpServerConfig(name="lazy-srv", command="false", lazy=True),
        ]
    )
    summary = await manager.start_all()
    assert summary.ready == []
    assert summary.failed == []
    await manager.stop_all()


# ── Claude Code interop ──────────────────────────────────────────────────


def _make_claude_layout(base: Path) -> Path:
    """cache/<marketplace>/<plugin>/<version>/ + installed_plugins.json v2."""
    install = base / "cache" / "mp" / "warp" / "1.0.0"
    (install / ".claude-plugin").mkdir(parents=True)
    (install / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "warp", "version": "1.0.0", "description": "cc"}),
        encoding="utf-8",
    )
    (base / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "warp@mp": [
                        {"scope": "user", "installPath": str(install)}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return install


def test_discover_claude_plugins_via_lockfile(tmp_path: Path) -> None:
    install = _make_claude_layout(tmp_path)
    found = discover_claude_plugins(tmp_path)
    assert [(m.name, p) for m, p in found] == [("warp", install)]


def test_discover_claude_plugins_walk_fallback(tmp_path: Path) -> None:
    install = _make_claude_layout(tmp_path)
    (tmp_path / "installed_plugins.json").unlink()
    found = discover_claude_plugins(tmp_path)
    assert [(m.name, p) for m, p in found] == [("warp", install)]


def test_discover_plugins_includes_claude_scope(
    tmp_path: Path, monkeypatch
) -> None:
    claude_dir = tmp_path / "claude-plugins"
    _make_claude_layout(claude_dir)
    monkeypatch.setenv("CLAUDE_PLUGINS_DIR", str(claude_dir))
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins = discover_plugins(workspace=tmp_path / "ws")
    warp = [p for p in plugins if p.name == "warp"]
    assert warp and warp[0].scope == "claude"
    assert warp[0].enabled and not warp[0].trusted


def test_claude_plugin_trust_state_in_user_lockfile(
    tmp_path: Path, monkeypatch
) -> None:
    claude_dir = tmp_path / "claude-plugins"
    _make_claude_layout(claude_dir)
    monkeypatch.setenv("CLAUDE_PLUGINS_DIR", str(claude_dir))
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    # Trust/disable stores state in our user lockfile, never in ~/.claude.
    assert "Trusted" in set_plugin_trusted("warp", True)
    assert "Disabled" in set_plugin_enabled("warp", False)
    plugins = discover_plugins(workspace=tmp_path / "ws", include_disabled=True)
    warp = [p for p in plugins if p.name == "warp"][0]
    assert warp.trusted and not warp.enabled
    assert not (claude_dir / "installed_plugins.json").read_text().count("trusted")


# ── Marketplace registry ─────────────────────────────────────────────────


def test_plugin_registry_document_parsing() -> None:
    doc = PluginRegistryDocument.from_json(
        json.dumps(
            {
                "plugins": {
                    "demo": {
                        "source": "github:owner/demo",
                        "description": "A demo",
                        "version": "1.0.0",
                        "components": ["skills", "mcp"],
                        "permissions": ["read"],
                    },
                    "broken": {"description": "no source"},
                }
            }
        )
    )
    assert len(doc.plugins) == 1
    entry = doc.plugins[0]
    assert entry.name == "demo"
    assert entry.source == "github:owner/demo"
    assert entry.components == ("skills", "mcp")
    assert entry.permissions == ("read",)


# ── Engine integration ───────────────────────────────────────────────────


async def test_tool_runtime_receives_plugin_mcp_servers(tmp_path: Path) -> None:
    """Plugin MCP server configs flow into the McpManager (not started)."""
    from deepseek_tui.config.models import Config
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.tools.runtime import create_tool_runtime

    cfg = Config(
        features={"tasks": False, "subagents": False, "mcp": True},
        mcp_config_path=tmp_path / "mcp.json",
    )
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=tmp_path,
        extra_mcp_servers=[McpServerConfig(name="demo-srv", command="cat")],
    )
    try:
        assert runtime.mcp_manager is not None
        assert "demo-srv" in runtime.mcp_manager.server_names
    finally:
        await runtime.shutdown()


async def test_engine_create_loads_plugin_components(tmp_path, monkeypatch) -> None:
    """End-to-end: trusted plugin's skill reaches the SkillRegistry and its
    hook reaches the HookExecutor via Engine.create."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(plugins_dir, "demo", with_mcp=False)
    set_plugin_trusted("demo", True, plugins_dir)

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(),
        AsyncMock(),
        config=cfg,
        working_directory=workspace,
    )
    try:
        assert engine.skill_registry.get("demo-skill") is not None
        assert engine.hook_executor is not None
        assert engine.hook_executor.has_hooks_for_event("session_start")
        hook_names = [h.name for h in engine.hook_executor.config.hooks]
        assert "demo:session_start" in hook_names
    finally:
        await engine.shutdown_session()
