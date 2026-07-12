"""Plugin system tests — manifest parsing, discovery, lockfile lifecycle,
contribution fan-out, and Engine.create integration."""

from __future__ import annotations

import json
import shutil
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
    update_plugin,
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
    with_command: bool = False,
    with_agent: bool = False,
    declare_components: bool = True,
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
        if declare_components:
            manifest["skills"] = "./skills"
    if with_command:
        cmds = plugin / "commands"
        cmds.mkdir(parents=True)
        (cmds / "greet.md").write_text(
            "---\ndescription: Greet someone.\nargument-hint: <name>\n---\n"
            "Say hello to $ARGUMENTS in a friendly way.\n",
            encoding="utf-8",
        )
        if declare_components:
            manifest["commands"] = "./commands"
    if with_agent:
        agents = plugin / "agents"
        agents.mkdir(parents=True)
        (agents / "specialist.md").write_text(
            "---\nname: demo-specialist\ndescription: A specialist persona.\n"
            "model: opus\ntools: Read, Grep\n---\n"
            "You are a focused specialist. Do the task well.\n",
            encoding="utf-8",
        )
        if declare_components:
            manifest["agents"] = "./agents"
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
        tmp_path,
        extra_manifest={"outputStyles": "./styles", "lspServers": "./lsp"},
    )
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert set(manifest.unsupported) == {"outputStyles", "lspServers"}


def test_manifest_missing_returns_none(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert load_plugin_manifest(tmp_path / "empty") is None


def make_codebuddy_plugin(root: Path, name: str = "cb") -> Path:
    """A CodeBuddy-style plugin: ``.codebuddy-plugin`` manifest, skills declared
    as leaf dirs, agents/rules declared as .md files."""
    plugin = root / name
    (plugin / "skills" / "alpha-skill").mkdir(parents=True)
    (plugin / "skills" / "alpha-skill" / "SKILL.md").write_text(
        "---\nname: fsi-alpha\ndescription: Alpha skill.\n---\nAlpha body.\n",
        encoding="utf-8",
    )
    (plugin / "agents").mkdir(parents=True)
    (plugin / "agents" / "worker.md").write_text(
        "---\nname: cb_worker\ndescription: A worker.\n"
        "tools: Glob, Grep\nmodel: claude-haiku-4.5\n---\nYou are a worker.\n",
        encoding="utf-8",
    )
    (plugin / "rules").mkdir(parents=True)
    (plugin / "rules" / "core.md").write_text(
        "---\ndescription: Core directive.\nalwaysApply: true\nenabled: true\n---\n"
        "You MUST follow the core workflow.\n",
        encoding="utf-8",
    )
    (plugin / "rules" / "disabled.md").write_text(
        "---\ndescription: off.\nenabled: false\n---\nShould not load.\n",
        encoding="utf-8",
    )
    mdir = plugin / ".codebuddy-plugin"
    mdir.mkdir(parents=True)
    (mdir / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "1.0.0",
                "description": "codebuddy plugin",
                "skills": ["./skills/alpha-skill"],
                "agents": ["./agents/worker.md"],
                "rules": ["./rules/core.md", "./rules/disabled.md"],
            }
        ),
        encoding="utf-8",
    )
    return plugin


def test_codebuddy_manifest_location_recognized(tmp_path: Path) -> None:
    plugin = make_codebuddy_plugin(tmp_path)
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.name == "cb"
    assert manifest.skills == ("./skills/alpha-skill",)
    assert manifest.agents == ("./agents/worker.md",)
    assert manifest.rules == ("./rules/core.md", "./rules/disabled.md")


def test_codebuddy_leaf_skills_files_agents_and_rules(tmp_path: Path) -> None:
    make_codebuddy_plugin(tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    # Leaf skill dir (SKILL.md directly inside) loads.
    assert [s.name for s in contribs.skills] == ["fsi-alpha"]
    # Agent declared as a .md file loads.
    assert [a.name for a in contribs.agents] == ["cb_worker"]
    assert contribs.agents[0].model == "claude-haiku-4.5"
    assert contribs.agents[0].tools == ("Glob", "Grep")
    # Rules: enabled core loads, disabled one is skipped.
    assert [r.name for r in contribs.rules] == ["core"]
    assert contribs.rules[0].always_apply is True
    assert "core workflow" in contribs.rules[0].body


def test_bare_skill_folder_synthesizes_single_skill_plugin(tmp_path: Path) -> None:
    # A folder whose root holds SKILL.md and no manifest (CodeBuddy/WorkBuddy
    # standalone skills like ardot-slides / pptx-generator).
    plugin = tmp_path / "ardot-slides"
    plugin.mkdir()
    (plugin / "SKILL.md").write_text(
        "---\nname: ardot-slides\ndescription: Slide design.\n---\nDeck workflow.\n",
        encoding="utf-8",
    )
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.name == "ardot-slides"
    assert manifest.skills == (".",)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert [s.name for s in contribs.skills] == ["ardot-slides"]


def test_codebuddy_hooks_schema_parsed(tmp_path: Path) -> None:
    plugin = tmp_path / "ppt"
    (plugin / ".codebuddy-plugin").mkdir(parents=True)
    (plugin / "hooks").mkdir()
    (plugin / ".codebuddy-plugin" / "plugin.json").write_text(
        json.dumps(
            {"name": "ppt", "version": "1.0.0", "hooks": "./hooks/hooks.json"}
        ),
        encoding="utf-8",
    )
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'node "${CODEBUDDY_PLUGIN_ROOT}/x.js" '
                                    '"${CODEBUDDY_PROJECT_DIR}"',
                                    "timeout": 10000,
                                }
                            ]
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "Skill",
                            "hooks": [{"type": "command", "command": "echo pre"}],
                        }
                    ],
                    "Stop": [
                        {"hooks": [{"type": "command", "command": "echo stop"}]}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    set_plugin_trusted("ppt", True, plugins_dir=tmp_path)  # hooks need trust
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    events = {h.event: h for h in contribs.hook_entries}
    assert "session_start" in events
    assert "tool_call_before" in events
    # Timeout ms -> seconds.
    assert events["session_start"].timeout_secs == 10.0
    # Plugin-root token resolved to absolute path; project-dir -> runtime env.
    assert "${CODEBUDDY_PLUGIN_ROOT}" not in events["session_start"].command
    assert "${DEEPSEEK_WORKSPACE}" in events["session_start"].command
    # matcher mapped to our tool taxonomy so the hook actually fires.
    assert events["tool_call_before"].condition == {
        "type": "tool_name_any",
        "names": ["load_skill"],
    }
    # Unsupported event skipped with a warning.
    assert any("Stop" in w for w in contribs.warnings)


def test_current_date_template_substituted_in_rules(tmp_path: Path) -> None:
    from deepseek_tui.engine.prompts import (
        render_plugin_rules_context,
        substitute_builtin_template_vars,
    )

    assert "{{.CurrentDate}}" not in substitute_builtin_template_vars(
        "today is {{.CurrentDate}}"
    )
    assert "{{.Other}}" in substitute_builtin_template_vars("keep {{.Other}}")
    plugin = tmp_path / "dr"
    (plugin / ".codebuddy-plugin").mkdir(parents=True)
    (plugin / "rules").mkdir()
    (plugin / ".codebuddy-plugin" / "plugin.json").write_text(
        json.dumps(
            {"name": "dr", "version": "1.0.0", "rules": ["./rules/r.md"]}
        ),
        encoding="utf-8",
    )
    (plugin / "rules" / "r.md").write_text(
        "---\ndescription: d\nalwaysApply: true\n---\nThe date is {{.CurrentDate}}.\n",
        encoding="utf-8",
    )
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    ctx = render_plugin_rules_context(contribs.rules)
    assert "{{.CurrentDate}}" not in ctx
    assert "The date is" in ctx


def test_rules_autodiscovered_without_manifest_key(tmp_path: Path) -> None:
    plugin = tmp_path / "cb2"
    (plugin / "rules").mkdir(parents=True)
    (plugin / "rules" / "r.md").write_text(
        "---\ndescription: d\n---\nRule body.\n", encoding="utf-8"
    )
    (plugin / ".codebuddy-plugin").mkdir(parents=True)
    (plugin / ".codebuddy-plugin" / "plugin.json").write_text(
        json.dumps({"name": "cb2", "version": "1.0.0"}), encoding="utf-8"
    )
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.rules == ("./rules",)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert [r.name for r in contribs.rules] == ["r"]


def test_load_marketplace_resolves_local_plugins(tmp_path: Path) -> None:
    from deepseek_tui.integrations.plugins import load_marketplace

    repo = tmp_path / "repo"
    (repo / "plugins").mkdir(parents=True)
    make_plugin(repo / "plugins", "alpha", with_hook=False, with_mcp=False)
    make_plugin(repo / "plugins", "beta", with_hook=False, with_mcp=False)
    market = repo / ".claude-plugin"
    market.mkdir(parents=True)
    (market / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "demo-market",
                "plugins": [
                    {"name": "alpha", "source": "./plugins/alpha"},
                    {"name": "beta", "source": "./plugins/beta"},
                    # Remote git-subdir entries are skipped.
                    {"name": "remote", "source": {"source": "git-subdir"}},
                ],
            }
        ),
        encoding="utf-8",
    )
    entries = load_marketplace(repo)
    assert {e.name for e in entries} == {"alpha", "beta"}
    assert all(e.path.is_dir() for e in entries)


def test_manifest_autodiscovers_components_without_declaration(tmp_path: Path) -> None:
    # Mainstream (Claude Code) plugins ship a minimal manifest and lay
    # components out as directories; auto-discovery must find all three.
    plugin = make_plugin(
        tmp_path,
        with_command=True,
        with_agent=True,
        declare_components=False,
        with_hook=False,
        with_mcp=False,
    )
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.skills == ("./skills",)
    assert manifest.commands == ("./commands",)
    assert manifest.agents == ("./agents",)


def test_collect_commands_and_agents(tmp_path: Path) -> None:
    make_plugin(
        tmp_path,
        with_command=True,
        with_agent=True,
        with_hook=False,
        with_mcp=False,
    )
    loaded = discover_plugins(plugins_dir=tmp_path)
    contribs = collect_contributions(loaded)
    assert len(contribs.commands) == 1
    cmd = contribs.commands[0]
    assert cmd.qualified == "demo:greet"
    assert cmd.argument_hint == "<name>"
    assert "$ARGUMENTS" in cmd.body
    assert len(contribs.agents) == 1
    agent = contribs.agents[0]
    assert agent.name == "demo-specialist"
    assert agent.model == "opus"
    assert agent.tools == ("Read", "Grep")
    assert "specialist" in agent.body.lower()


def test_collect_command_no_frontmatter_falls_back_to_body(tmp_path: Path) -> None:
    plugin = tmp_path / "bare"
    (plugin / "commands").mkdir(parents=True)
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "bare", "version": "1.0.0"}), encoding="utf-8"
    )
    (plugin / "commands" / "raw.md").write_text(
        "Just a bare command body with no frontmatter.\n", encoding="utf-8"
    )
    loaded = discover_plugins(plugins_dir=tmp_path)
    contribs = collect_contributions(loaded)
    assert len(contribs.commands) == 1
    assert contribs.commands[0].qualified == "bare:raw"
    assert "bare command body" in contribs.commands[0].body


def test_commands_and_agents_load_even_when_untrusted(tmp_path: Path) -> None:
    # Declarative text (like skills) must load regardless of trust; only
    # hooks/MCP are trust-gated.
    make_plugin(tmp_path, with_command=True, with_agent=True)
    loaded = discover_plugins(plugins_dir=tmp_path)
    assert all(not p.trusted for p in loaded)
    contribs = collect_contributions(loaded)
    assert contribs.commands and contribs.agents
    # hooks/MCP skipped while untrusted
    assert not contribs.hook_entries
    assert not contribs.mcp_servers


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
    # Bare absolute path (not ``local:<path>``) so the recorded source can
    # round-trip through InstallSource.parse when update_plugin re-resolves it.
    assert entry["source"] == str(src.resolve())
    assert entry["version"] == "1.2.3"
    assert entry["enabled"] is True and entry["trusted"] is False

    # Duplicate install refuses.
    outcome, _ = install_plugin(str(src), target)
    assert outcome == InstallOutcome.ALREADY_EXISTS

    # The recorded local source must be updatable (regression: previously the
    # ``local:`` prefix made InstallSource.parse reject it).
    outcome, _ = update_plugin("demo", target)
    assert outcome == InstallOutcome.UPDATED


def test_update_failure_preserves_existing_plugin(tmp_path: Path) -> None:
    """A failed re-install must not delete the live plugin (staging swap).

    Regression: update_plugin used to rmtree the plugin dir before installing,
    so any failure left the plugin gone.
    """
    src = make_plugin(tmp_path / "src")
    target = tmp_path / "installed"
    install_plugin(str(src), target)
    # Point the recorded source at a now-missing dir so re-install fails.
    shutil.rmtree(src)
    outcome, _ = update_plugin("demo", target)
    assert outcome == InstallOutcome.FAILED
    # Live copy and its manifest survive the failed update.
    assert (target / "demo").is_dir()
    assert load_plugin_manifest(target / "demo") is not None


def test_update_refreshes_live_lockfile_version(tmp_path: Path) -> None:
    """Successful update must write the new version onto the live lockfile.

    Staging's lockfile is discarded with the staging dir; only the live
    ``installed_plugins.json`` matters after swap.
    """
    src = make_plugin(tmp_path / "src")
    target = tmp_path / "installed"
    install_plugin(str(src), target)
    assert read_lockfile(target)["demo"]["version"] == "1.2.3"

    # Bump the source manifest version, then update.
    mpath = src / ".deepseek-plugin" / "plugin.json"
    data = json.loads(mpath.read_text(encoding="utf-8"))
    data["version"] = "9.9.9"
    mpath.write_text(json.dumps(data), encoding="utf-8")

    outcome, _ = update_plugin("demo", target)
    assert outcome == InstallOutcome.UPDATED
    entry = read_lockfile(target)["demo"]
    assert entry["version"] == "9.9.9"
    assert entry["source"] == str(src.resolve())
    assert entry["enabled"] is True
    assert (target / "demo").is_dir()
    assert not (target / ".update-staging-demo").exists()
    assert not (target / ".update-backup-demo").exists()


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


def test_declared_capabilities_prefix_match_without_tool_map() -> None:
    """Caps resolve for a hyphenated plugin server before discovery runs.

    Regression: the ambiguous ``parse_qualified_tool_name`` fallback split
    ``mcp_demo_srv_run`` as ("demo", "srv_run"), so ``_configs.get("demo")``
    missed the real ``demo-srv`` server and returned no capabilities —
    breaking the read-only approval relaxation for lazy plugin servers whose
    tool map isn't populated yet.
    """
    from deepseek_tui.mcp.client import qualify_tool_name
    from deepseek_tui.mcp.config import McpServerConfig
    from deepseek_tui.mcp.manager import McpManager

    manager = McpManager(
        [McpServerConfig(name="demo-srv", command="cat", capabilities=["read_only"])]
    )
    qualified = qualify_tool_name("demo-srv", "run")
    assert manager.declared_capabilities(qualified) == ["read_only"]


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


async def test_engine_registers_plugin_commands_and_agents(
    tmp_path, monkeypatch
) -> None:
    """Plugin commands + agent personas reach the engine: commands expand
    into messages, agents are exposed to agent_spawn via metadata."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(
        plugins_dir,
        "demo",
        with_command=True,
        with_agent=True,
        with_hook=False,
        with_mcp=False,
    )

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        assert "demo:greet" in engine.plugin_commands
        assert "demo-specialist" in engine.plugin_agents
        assert "plugin_agents" in engine.tool_context.metadata

        # Command expansion substitutes $ARGUMENTS.
        expanded = engine._expand_plugin_command("/demo:greet World")
        assert expanded is not None
        assert "World" in expanded
        assert "$ARGUMENTS" not in expanded

        # Non-command messages and unknown commands pass through.
        assert engine._expand_plugin_command("hello there") is None
        assert engine._expand_plugin_command("/demo:missing x") is None

        # Components surface in the system prompt block.
        block = engine._render_plugin_components_context()
        assert block is not None
        assert "/demo:greet" in block
        assert "demo-specialist" in block
    finally:
        await engine.shutdown_session()


async def test_agent_spawn_resolves_plugin_persona(tmp_path) -> None:
    """agent_spawn resolves a plugin agent name to a CUSTOM/general spawn
    whose system prompt is the persona body."""
    from deepseek_tui.integrations.plugins import PluginAgent
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.subagent.manager import SubAgentManager
    from deepseek_tui.tools.subagent.tools import AgentSpawnTool

    persona = PluginAgent(
        name="demo-specialist",
        plugin="demo",
        description="A specialist.",
        body="You are a focused specialist persona.",
        path=tmp_path / "a.md",
        model="opus",
        tools=("Read", "Grep"),
    )
    manager = SubAgentManager(workspace=tmp_path)
    context = ToolContext(
        working_directory=tmp_path,
        subagent_manager=manager,
        metadata={"plugin_agents": {"demo-specialist": persona}},
    )
    result = await AgentSpawnTool().execute(
        {"prompt": "do the thing", "type": "demo-specialist"}, context
    )
    assert result.success
    agent_id = result.metadata["agent_id"]
    spawned = manager._agents[agent_id]
    assert spawned.system_prompt == "You are a focused specialist persona."
    # Unknown persona names still raise.
    import pytest

    from deepseek_tui.tools.registry import ToolError

    with pytest.raises(ToolError):
        await AgentSpawnTool().execute(
            {"prompt": "x", "type": "nonexistent-agent"}, context
        )
    await manager.shutdown()


async def test_load_skill_resolves_plugin_skill_via_engine_registry(
    tmp_path, monkeypatch
) -> None:
    """load_skill resolves plugin skills by name via the engine's merged
    registry exposed in tool_context.metadata.

    Regression: plugin skills are merged into engine.skill_registry in
    Engine.create (and listed in the system prompt), but load_skill used to
    re-discover via discover_in_workspace - which does NOT merge plugin
    contributions - so load_skill(name=...) returned 'not found' for any
    plugin skill. The engine now exposes its registry in metadata and
    load_skill prefers it.
    """
    from unittest.mock import AsyncMock
    import pytest

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(plugins_dir, "demo", with_hook=False, with_mcp=False)
    set_plugin_trusted("demo", True, plugins_dir)

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.tools.knowledge import SkillLoadTool
    from deepseek_tui.tools.registry import ToolContext, ToolError

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        # The engine exposes its merged registry (incl. the plugin skill) in
        # tool_context.metadata, which is what load_skill reads.
        reg = engine.tool_context.metadata.get("skill_registry")
        assert reg is not None
        assert reg.get("demo-skill") is not None

        tool = SkillLoadTool()
        # load_skill(name=...) now resolves the plugin skill (previously
        # 'not found' because discover_in_workspace skips plugin skills).
        result = await tool.execute({"name": "demo-skill"}, engine.tool_context)
        assert result.success
        assert result.content  # the SKILL.md body

        # Engine-less context (no metadata) falls back to discover_in_workspace,
        # which does NOT include plugin skills -> the plugin skill is
        # unreachable. This proves the metadata path is what fixes it.
        bare_ctx = ToolContext(working_directory=workspace)
        with pytest.raises(ToolError):
            await tool.execute({"name": "demo-skill"}, bare_ctx)
    finally:
        await engine.shutdown_session()


# ── @plugin:name mount (session-level focus) ──────────────────────────────


def test_detect_plugin_mount_distinguishes_prefixes() -> None:
    """`@plugin:name` mounts; bare `@mcp` / `/skill` / plain text do not."""
    from deepseek_tui.engine.orchestrator.helpers import _detect_plugin_mount

    assert _detect_plugin_mount("@plugin:hello-probe run the probe") == "hello-probe"
    assert _detect_plugin_mount("@plugin:off") == "off"
    assert _detect_plugin_mount("@plugin:none") == "off"
    assert _detect_plugin_mount("@plugin:") == "off"
    # bare @mcp connector focus, not a plugin mount
    assert _detect_plugin_mount("@github look here") is None
    # skill focus prefix
    assert _detect_plugin_mount("/data-extract go") is None
    # plain text
    assert _detect_plugin_mount("just a normal question") is None
    # only the FIRST token counts (focus semantics)
    assert _detect_plugin_mount("look @plugin:foo") is None


def test_strip_plugin_mount_removes_prefix() -> None:
    from deepseek_tui.engine.orchestrator.helpers import _strip_plugin_mount

    assert _strip_plugin_mount("@plugin:hello run it", "hello") == "run it"
    assert _strip_plugin_mount("@plugin:off", "off") == ""
    assert _strip_plugin_mount("@plugin:none rest", "off") == "rest"


async def test_active_plugin_whitelist_read_only(tmp_path, monkeypatch) -> None:
    """A read-permission plugin narrows to read-only base tools (no write)."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(
        plugins_dir,
        "ro-plugin",
        with_mcp=False,
        with_hook=False,
        extra_manifest={"permissions": ["read"]},
    )
    set_plugin_trusted("ro-plugin", True, plugins_dir)

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        note = engine.set_active_plugin("ro-plugin")
        assert "ro-plugin" in note
        wl = engine._active_plugin_whitelist()
        assert wl is not None
        # Read-only plugin gets the full read base (grep_files, not the old
        # buggy "grep"; plus file_search, git read, project_map, ...).
        assert {"read_file", "grep_files", "list_dir", "load_skill"} <= wl
        assert {"file_search", "git_status", "git_diff", "project_map"} <= wl
        # No write tools for a read-only plugin (incl. apply_patch).
        assert {"write_file", "edit_file", "apply_patch"}.isdisjoint(wl)
        # No exec either.
        assert {"exec_shell", "code_execution"}.isdisjoint(wl)
    finally:
        await engine.shutdown_session()


async def test_active_plugin_whitelist_write_permission(tmp_path, monkeypatch) -> None:
    """A write-permission plugin adds write_file/edit_file to the whitelist."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(
        plugins_dir,
        "rw-plugin",
        with_mcp=False,
        with_hook=False,
        extra_manifest={"permissions": ["write"]},
    )
    set_plugin_trusted("rw-plugin", True, plugins_dir)

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        engine.set_active_plugin("rw-plugin")
        wl = engine._active_plugin_whitelist()
        assert wl is not None
        assert {"write_file", "edit_file", "apply_patch"} <= wl
        # Read base still present alongside writes.
        assert {"read_file", "grep_files", "file_search"} <= wl
        # clearing restores full toolset (None sentinel)
        engine.set_active_plugin("off")
        assert engine._active_plugin_whitelist() is None
    finally:
        await engine.shutdown_session()


# ── Trust gate + plugin_context prompt block + restore ───────────────────


async def test_active_plugin_whitelist_trust_gate_blocks_mcp(
    tmp_path, monkeypatch
) -> None:
    """The explicit ``if plugin.trusted`` gate in _active_plugin_whitelist
    excludes MCP tool names even if collect_contributions were to return
    servers for an untrusted plugin (defense in depth vs future refactors)."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(plugins_dir, "mcp-plugin", with_hook=False)  # has MCP, untrusted

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.integrations import plugins as plugin_mod
    from deepseek_tui.integrations.plugins import PluginContributions
    from deepseek_tui.mcp.config import McpServerConfig

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        engine.set_active_plugin("mcp-plugin")
        assert engine._active_plugin is not None
        assert not engine._active_plugin.trusted  # sanity: untrusted

        # Bypass collect_contributions's own trust gating: return a server
        # anyway, and stub _server_tool_names, to prove the explicit gate in
        # _active_plugin_whitelist is what blocks the name (not the absence of
        # contributed servers).
        fake_contribs = PluginContributions(
            mcp_servers=[McpServerConfig(name="mcp-plugin-srv", command="cat")]
        )
        monkeypatch.setattr(
            plugin_mod, "collect_contributions", lambda *a, **k: fake_contribs
        )
        engine._server_tool_names = lambda server: frozenset(  # type: ignore[assignment]
            {"mcp_mcp-plugin-srv__do"}
        )

        wl = engine._active_plugin_whitelist()
        assert wl is not None
        assert "mcp_mcp-plugin-srv__do" not in wl  # gate blocked (untrusted)

        # Trust + re-mount -> gate allows the name through.
        set_plugin_trusted("mcp-plugin", True, plugins_dir)
        engine.set_active_plugin("mcp-plugin")
        wl2 = engine._active_plugin_whitelist()
        assert wl2 is not None
        assert "mcp_mcp-plugin-srv__do" in wl2
    finally:
        await engine.shutdown_session()


async def test_plugin_mount_confines_advanced_meta_tools(
    tmp_path, monkeypatch
) -> None:
    """Mounting a read-only plugin confines code_execution + tool_search.

    Regression: ``ensure_advanced_tooling`` re-added these meta-tools to the
    catalog AFTER the focus whitelist filter, so a ``permissions: ["read"]``
    plugin still left ``code_execution`` (arbitrary Python incl.
    ``subprocess``) callable - breaking the read-only confinement.
    ``_advanced_tool_flags`` now gates them by the whitelist.
    """
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(
        plugins_dir,
        "ro-plugin",
        with_mcp=False,
        with_hook=False,
        extra_manifest={"permissions": ["read"]},
    )
    set_plugin_trusted("ro-plugin", True, plugins_dir)

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        engine.set_active_plugin("ro-plugin")
        engine._focus_tool_whitelist = engine._active_plugin_whitelist()
        # read-only plugin whitelist has only read tools -> both meta-tools
        # confined (this is the regression: previously code_execution stayed
        # available via ensure_advanced_tooling bypassing the whitelist).
        assert engine._advanced_tool_flags() == (False, False)

        # If the whitelist explicitly lists code_execution (e.g. a plugin
        # skill declared it via allowed-tools), it is allowed through.
        engine._focus_tool_whitelist = frozenset({"read_file", "code_execution"})
        assert engine._advanced_tool_flags() == (False, True)

        # tool_search同理: only when whitelisted.
        engine._focus_tool_whitelist = frozenset(
            {"read_file", "tool_search_tool_bm25", "tool_search_tool_regex"}
        )
        assert engine._advanced_tool_flags() == (True, False)

        # No whitelist -> normal profile defaults (both included when full).
        engine._focus_tool_whitelist = None
        _search, _code = engine._advanced_tool_flags()
        assert _code is True  # tool_profile None -> code_execution included
    finally:
        await engine.shutdown_session()


async def test_render_plugin_context_block_includes_path_and_read_grant(
    tmp_path, monkeypatch
) -> None:
    """The ## Active Plugin block tells the model the plugin directory and
    that reads under it are permitted (paired with extra_read_roots)."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(
        plugins_dir,
        "ro",
        with_mcp=False,
        with_hook=False,
        extra_manifest={"permissions": ["read"]},
    )
    set_plugin_trusted("ro", True, plugins_dir)

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        engine.set_active_plugin("ro")
        block = engine._render_plugin_context()
        assert block is not None
        assert "## Active Plugin" in block
        assert 'plugin "ro"' in block
        # The resolved plugin directory path is communicated to the model.
        assert str((plugins_dir / "ro").resolve()) in block
        # The read grant is stated explicitly (overrides path-escape rule).
        assert "read_file / list_dir / grep" in block
        assert "OVERRIDES the path-escape rule" in block
        assert "Declared permissions: read" in block
        # No MCP -> no inactive-MCP note.
        assert "MCP servers from this plugin are NOT active" not in block

        # Unmount -> no block.
        engine.set_active_plugin("off")
        assert engine._render_plugin_context() is None
    finally:
        await engine.shutdown_session()


async def test_render_plugin_context_notes_inactive_mcp_when_untrusted(
    tmp_path, monkeypatch
) -> None:
    """An untrusted plugin with MCP gets a 'MCP NOT active' line in the block."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(plugins_dir, "mcp-untrusted", with_hook=False)  # has MCP, untrusted

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        engine.set_active_plugin("mcp-untrusted")
        block = engine._render_plugin_context()
        assert block is not None
        assert "MCP servers from this plugin are NOT active (plugin not trusted)" in block
    finally:
        await engine.shutdown_session()


def test_plugin_mount_info_roundtrip() -> None:
    """PluginMountInfo survives a to_metadata -> from_metadata round-trip;
    an unmounted sentinel (name=None) serializes to null."""
    from deepseek_tui.server.phase_bridge import PluginMountInfo

    info = PluginMountInfo(
        name="p",
        version="1.2.3",
        path="/abs/p",
        scope="user",
        trusted=True,
        permissions=("read", "network"),
        mcp_active=True,
    )
    raw = info.to_metadata()
    assert raw == {
        "name": "p",
        "version": "1.2.3",
        "path": "/abs/p",
        "scope": "user",
        "trusted": True,
        "permissions": ["read", "network"],
        "mcp_active": True,
    }
    assert PluginMountInfo.from_metadata(raw) == info
    # Unmount sentinel -> null payload; from_metadata(None) is no-signal.
    assert PluginMountInfo(name=None).to_metadata() is None
    assert PluginMountInfo.from_metadata(None) is None
    assert PluginMountInfo.from_metadata("not a dict") is None


async def test_restore_active_plugin_from_persisted_items(
    tmp_path, monkeypatch
) -> None:
    """_restore_active_plugin re-mounts the latest plugin from persisted
    STATUS items, and respects a later @plugin:off (null marker)."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    make_plugin(
        plugins_dir,
        "restorable",
        with_hook=False,
        with_mcp=False,
        extra_manifest={"permissions": ["read"]},
    )
    set_plugin_trusted("restorable", True, plugins_dir)

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.server.phase_bridge import (
        ACTIVE_PLUGIN_METADATA_KEY,
        PluginMountInfo,
    )
    from deepseek_tui.server.threads.manager import RuntimeThreadManager
    from deepseek_tui.server.threads.models import (
        RuntimeTurnStatus,
        ThreadRecord,
        TurnItemKind,
        TurnItemLifecycleStatus,
        TurnItemRecord,
        TurnRecord,
    )
    from deepseek_tui.server.threads.store import RuntimeThreadStore

    store = RuntimeThreadStore(tmp_path / "store")
    now = datetime.now(timezone.utc)
    thread = ThreadRecord(
        id="t1", created_at=now, updated_at=now, model="m", workspace=str(tmp_path)
    )
    store.save_thread(thread)
    turn = TurnRecord(
        id="turn1",
        thread_id="t1",
        status=RuntimeTurnStatus.COMPLETED,
        input_summary="mount",
        created_at=now,
    )
    store.save_turn(turn)
    info = PluginMountInfo(
        name="restorable",
        version="1.2.3",
        path=str(plugins_dir / "restorable"),
        scope="user",
        trusted=True,
        permissions=("read",),
        mcp_active=False,
    )
    mount_item = TurnItemRecord(
        id="i1",
        turn_id="turn1",
        kind=TurnItemKind.STATUS,
        status=TurnItemLifecycleStatus.COMPLETED,
        summary="mounted",
        detail="mounted",
        started_at=now,
        ended_at=now,
        metadata={ACTIVE_PLUGIN_METADATA_KEY: info.to_metadata()},
    )
    store.save_item(mount_item)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    stub = SimpleNamespace(store=store)
    try:
        assert engine._active_plugin is None
        RuntimeThreadManager._restore_active_plugin(stub, engine, thread)
        assert engine._active_plugin is not None
        assert engine._active_plugin.name == "restorable"

        # A later @plugin:off (null marker) must win -> restore stays unmounted.
        later = datetime.now(timezone.utc)
        turn2 = TurnRecord(
            id="turn2",
            thread_id="t1",
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="off",
            created_at=later,
        )
        store.save_turn(turn2)
        unmount_item = TurnItemRecord(
            id="i2",
            turn_id="turn2",
            kind=TurnItemKind.STATUS,
            status=TurnItemLifecycleStatus.COMPLETED,
            summary="unmounted",
            detail="off",
            started_at=later,
            ended_at=later,
            metadata={ACTIVE_PLUGIN_METADATA_KEY: None},
        )
        store.save_item(unmount_item)
        engine.set_active_plugin("off")
        assert engine._active_plugin is None
        RuntimeThreadManager._restore_active_plugin(stub, engine, thread)
        assert engine._active_plugin is None  # latest signal was unmount
    finally:
        await engine.shutdown_session()
