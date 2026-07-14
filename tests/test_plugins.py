"""Plugin system tests — manifest parsing, discovery, lockfile lifecycle,
contribution fan-out, and Engine.create integration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

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
    reindex_contribution_indexes,
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


# ── Claude-convention auto-discovery (manifest optional) ────────────────


def _write_foreign_hooks_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {"type": "command", "command": "echo hi"}
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def test_manifestless_layout_dir_synthesizes_plugin(tmp_path: Path) -> None:
    # Claude Code spec: the manifest is optional — components are discovered
    # from the conventional directory layout.
    plugin = tmp_path / "layout-only"
    (plugin / "skills" / "s1").mkdir(parents=True)
    (plugin / "skills" / "s1" / "SKILL.md").write_text(
        "---\nname: s1\ndescription: One.\n---\nBody.\n", encoding="utf-8"
    )
    (plugin / "agents").mkdir()
    (plugin / "agents" / "a1.md").write_text(
        "---\nname: a1\ndescription: Agent.\n---\nPersona.\n", encoding="utf-8"
    )
    _write_foreign_hooks_json(plugin / "hooks" / "hooks.json")
    (plugin / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"srv": {"command": "run"}}}), encoding="utf-8"
    )
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.name == "layout-only"
    assert manifest.skills == ("./skills",)
    assert manifest.agents == ("./agents",)
    assert manifest.hooks == ("./hooks/hooks.json",)
    assert manifest.mcp_servers == "./.mcp.json"


def test_manifestless_dir_without_components_is_not_a_plugin(tmp_path: Path) -> None:
    plugin = tmp_path / "random"
    (plugin / "docs").mkdir(parents=True)
    (plugin / "docs" / "readme.md").write_text("hi\n", encoding="utf-8")
    assert load_plugin_manifest(plugin) is None


def test_manifest_omitting_hooks_key_discovers_hooks_json(
    tmp_path: Path, monkeypatch
) -> None:
    # financial-analysis (WorkBuddy) case: hooks/hooks.json on disk but no
    # ``hooks`` key in the manifest. Claude Code loads it by convention.
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugin = make_plugin(tmp_path, with_hook=False, with_mcp=False)
    _write_foreign_hooks_json(plugin / "hooks" / "hooks.json")
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.hooks == ("./hooks/hooks.json",)
    lock = {"plugins": {"demo": {"enabled": True, "trusted": True}}}
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(lock), encoding="utf-8"
    )
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert [h.event for h in contribs.hook_entries] == ["session_start"]


def test_manifest_omitting_mcp_key_discovers_mcp_json(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugin = make_plugin(tmp_path, with_hook=False, with_mcp=False)
    (plugin / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"srv": {"command": "${PLUGIN_DIR}/bin/x"}}}),
        encoding="utf-8",
    )
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.mcp_servers == "./.mcp.json"
    lock = {"plugins": {"demo": {"enabled": True, "trusted": True}}}
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(lock), encoding="utf-8"
    )
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert [s.name for s in contribs.mcp_servers] == ["demo-srv"]
    assert contribs.mcp_servers[0].command == f"{plugin}/bin/x"


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
    # Full bodies (and thus template substitution) only ship when mounted.
    ctx = render_plugin_rules_context(contribs.rules, active_plugin="dr")
    assert "{{.CurrentDate}}" not in ctx
    assert "The date is" in ctx


def test_plugin_rules_context_mounted_vs_unmounted(tmp_path: Path) -> None:
    """Context governance: unmounted -> one summary line per plugin with a
    mount hint (no rule bodies); mounted -> only the mounted plugin's full
    rule bodies (other plugins' rules omitted)."""
    from deepseek_tui.engine.prompts import render_plugin_rules_context

    for name, body in (("alpha", "ALPHA-BODY-DIRECTIVE"), ("beta", "BETA-BODY")):
        plugin = tmp_path / name
        (plugin / ".codebuddy-plugin").mkdir(parents=True)
        (plugin / "rules").mkdir()
        (plugin / ".codebuddy-plugin" / "plugin.json").write_text(
            json.dumps(
                {"name": name, "version": "1.0.0", "rules": ["./rules/r.md"]}
            ),
            encoding="utf-8",
        )
        (plugin / "rules" / "r.md").write_text(
            f"---\ndescription: {name} scenario\nalwaysApply: true\n---\n{body}\n",
            encoding="utf-8",
        )
    rules = collect_contributions(discover_plugins(plugins_dir=tmp_path)).rules

    unmounted = render_plugin_rules_context(rules)
    assert "ALPHA-BODY-DIRECTIVE" not in unmounted
    assert "BETA-BODY" not in unmounted
    assert "alpha: alpha scenario" in unmounted
    assert "@plugin:<name>" in unmounted

    mounted = render_plugin_rules_context(rules, active_plugin="alpha")
    assert "ALPHA-BODY-DIRECTIVE" in mounted
    assert "BETA-BODY" not in mounted
    assert 'mounted plugin "alpha"' in mounted

    # Mounted plugin without rules -> empty block (not other plugins' rules).
    assert render_plugin_rules_context(rules, active_plugin="gamma") == ""


async def test_engine_mount_injects_own_rules(tmp_path, monkeypatch) -> None:
    """Regression: mounting used to suppress ALL plugin rules — including the
    mounted plugin's own, which carries its core behavior. Mounted -> own
    rule bodies injected; unmounted -> summary only."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    plugin = plugins_dir / "ruled"
    (plugin / ".codebuddy-plugin").mkdir(parents=True)
    (plugin / "rules").mkdir()
    (plugin / ".codebuddy-plugin" / "plugin.json").write_text(
        json.dumps(
            {"name": "ruled", "version": "1.0.0", "rules": ["./rules/r.md"]}
        ),
        encoding="utf-8",
    )
    (plugin / "rules" / "r.md").write_text(
        "---\ndescription: ruled scenario\nalwaysApply: true\n---\n"
        "RULED-CORE-DIRECTIVE\n",
        encoding="utf-8",
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
        unmounted = engine._render_plugin_rules_context()
        assert unmounted is not None
        assert "RULED-CORE-DIRECTIVE" not in unmounted
        assert "ruled" in unmounted

        engine.set_active_plugin("ruled")
        mounted = engine._render_plugin_rules_context()
        assert mounted is not None
        assert "RULED-CORE-DIRECTIVE" in mounted

        engine.set_active_plugin(None)
        assert "RULED-CORE-DIRECTIVE" not in (
            engine._render_plugin_rules_context() or ""
        )
    finally:
        await engine.shutdown_session()


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


# ── Registered marketplaces (two-level install model) ───────────────────


def make_marketplace_repo(root: Path, name: str = "demo-market") -> Path:
    repo = root / "repo"
    (repo / "plugins").mkdir(parents=True)
    make_plugin(repo / "plugins", "alpha", with_hook=False, with_mcp=False)
    make_plugin(repo / "plugins", "beta", with_hook=False, with_mcp=False)
    market = repo / ".claude-plugin"
    market.mkdir(parents=True)
    (market / "marketplace.json").write_text(
        json.dumps(
            {
                "name": name,
                "plugins": [
                    {"name": "alpha", "source": "./plugins/alpha"},
                    {"name": "beta", "source": "./plugins/beta"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return repo


def test_add_marketplace_local_registers_in_place(tmp_path: Path) -> None:
    from deepseek_tui.integrations.plugins import add_marketplace, read_marketplaces

    repo = make_marketplace_repo(tmp_path)
    base = tmp_path / "marketplaces"
    outcome, message = add_marketplace(str(repo), base)
    assert outcome == InstallOutcome.INSTALLED
    assert "demo-market" in message and "2 plugins" in message
    table = read_marketplaces(base)
    assert table["demo-market"]["source"] == str(repo.resolve())
    # Local marketplaces are referenced in place, not copied.
    assert table["demo-market"]["path"] == str(repo.resolve())
    assert not (base / "demo-market").exists()
    # Re-adding is idempotent.
    outcome, _ = add_marketplace(str(repo), base)
    assert outcome == InstallOutcome.ALREADY_EXISTS


def test_add_marketplace_without_marketplace_json_fails(tmp_path: Path) -> None:
    from deepseek_tui.integrations.plugins import add_marketplace

    plain = tmp_path / "plain"
    plain.mkdir()
    outcome, message = add_marketplace(str(plain), tmp_path / "marketplaces")
    assert outcome == InstallOutcome.FAILED
    assert "marketplace.json" in message


def test_install_plugin_at_marketplace_spec(tmp_path: Path) -> None:
    from deepseek_tui.integrations.plugins import add_marketplace

    repo = make_marketplace_repo(tmp_path)
    base = tmp_path / "marketplaces"
    add_marketplace(str(repo), base)
    plugins_dir = tmp_path / "plugins"

    import deepseek_tui.integrations.plugins as plugins_mod

    original = plugins_mod.marketplaces_dir
    plugins_mod.marketplaces_dir = lambda: base  # type: ignore[assignment]
    try:
        outcome, message = install_plugin("alpha@demo-market", plugins_dir)
        assert outcome == InstallOutcome.INSTALLED, message
        assert (plugins_dir / "alpha").is_dir()
        # Lockfile records the @ spec so update re-resolves the marketplace.
        assert read_lockfile(plugins_dir)["alpha"]["source"] == "alpha@demo-market"

        # Unknown plugin / marketplace fail with guidance.
        outcome, message = install_plugin("nope@demo-market", plugins_dir)
        assert outcome == InstallOutcome.FAILED
        assert "not found in marketplace" in message
        outcome, message = install_plugin("alpha@nowhere", plugins_dir)
        assert outcome == InstallOutcome.FAILED

        # update_plugin round-trips through the marketplace.
        outcome, message = update_plugin("alpha", plugins_dir)
        assert outcome == InstallOutcome.UPDATED, message
    finally:
        plugins_mod.marketplaces_dir = original  # type: ignore[assignment]


def test_remove_marketplace_never_deletes_local_checkout(tmp_path: Path) -> None:
    from deepseek_tui.integrations.plugins import (
        add_marketplace,
        read_marketplaces,
        remove_marketplace,
    )

    repo = make_marketplace_repo(tmp_path)
    base = tmp_path / "marketplaces"
    add_marketplace(str(repo), base)
    assert "not found" in remove_marketplace("nope", base)
    assert "Removed" in remove_marketplace("demo-market", base)
    assert read_marketplaces(base) == {}
    # The user's checkout is untouched (it lives outside the marketplaces dir).
    assert repo.is_dir()


def test_update_marketplace_local_is_noop(tmp_path: Path) -> None:
    from deepseek_tui.integrations.plugins import add_marketplace, update_marketplace

    repo = make_marketplace_repo(tmp_path)
    base = tmp_path / "marketplaces"
    add_marketplace(str(repo), base)
    outcome, message = update_marketplace("demo-market", base)
    assert outcome == InstallOutcome.UPDATED
    assert "local directory" in message


def test_scaffold_plugin_generates_loadable_skeleton(tmp_path: Path) -> None:
    from deepseek_tui.integrations.plugins import scaffold_plugin

    outcome, message = scaffold_plugin("my-plugin", tmp_path)
    assert outcome == InstallOutcome.INSTALLED
    dest = tmp_path / "my-plugin"
    assert (dest / ".claude-plugin" / "plugin.json").is_file()
    assert (dest / "skills" / "my-plugin" / "SKILL.md").is_file()
    # The skeleton loads through the real pipeline.
    manifest = load_plugin_manifest(dest)
    assert manifest is not None and manifest.name == "my-plugin"
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    assert [s.name for s in contribs.skills] == ["my-plugin"]
    # Bad names and existing dirs fail.
    assert scaffold_plugin("My_Plugin", tmp_path)[0] == InstallOutcome.FAILED
    assert scaffold_plugin("my-plugin", tmp_path)[0] == InstallOutcome.FAILED


def test_parse_plugin_at_marketplace() -> None:
    from deepseek_tui.integrations.plugins import parse_plugin_at_marketplace

    assert parse_plugin_at_marketplace("alpha@demo") == ("alpha", "demo")
    assert parse_plugin_at_marketplace("a.b-c@m_1") == ("a.b-c", "m_1")
    assert parse_plugin_at_marketplace("github:owner/repo") is None
    assert parse_plugin_at_marketplace("/some/path") is None
    assert parse_plugin_at_marketplace("@market") is None
    assert parse_plugin_at_marketplace("plugin@") is None


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


def test_frontmatter_uses_yaml_types_and_folded_text(tmp_path: Path) -> None:
    plugin = tmp_path / "yaml-plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / "commands").mkdir()
    (plugin / "agents").mkdir()
    (plugin / "rules").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "yaml-plugin", "version": "1.0.0"}),
        encoding="utf-8",
    )
    (plugin / "commands" / "explain.md").write_text(
        "---\ndescription: >-\n  Explain the result\n  in plain language.\n---\nDo it.\n",
        encoding="utf-8",
    )
    (plugin / "agents" / "reader.md").write_text(
        "---\nname: reader\ntools:\n  - Read\n  - Grep\n---\nRead carefully.\n",
        encoding="utf-8",
    )
    (plugin / "rules" / "disabled.md").write_text(
        "---\nenabled: false\n---\nNever loaded.\n",
        encoding="utf-8",
    )
    (plugin / "rules" / "opt-in.md").write_text(
        "---\nalwaysApply: false\n---\nOnly when selected.\n",
        encoding="utf-8",
    )

    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))

    assert contribs.commands[0].description == (
        "Explain the result in plain language."
    )
    assert contribs.agents[0].tools == ("Read", "Grep")
    assert [rule.name for rule in contribs.rules] == ["opt-in"]
    assert contribs.rules[0].always_apply is False


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


def test_claude_plugin_root_expands_in_mcp_config(tmp_path: Path) -> None:
    plugin = make_plugin(
        tmp_path,
        with_hook=False,
        extra_manifest={
            "mcpServers": {
                "srv": {
                    "command": "${CLAUDE_PLUGIN_ROOT}/bin/server",
                    "args": ["${CLAUDE_PLUGIN_ROOT}/config.json"],
                    "env": {"PLUGIN_HOME": "${CLAUDE_PLUGIN_ROOT}"},
                }
            }
        },
    )
    set_plugin_trusted("demo", True, tmp_path)

    server = collect_contributions(discover_plugins(plugins_dir=tmp_path)).mcp_servers[0]

    assert server.command == f"{plugin}/bin/server"
    assert server.args == [f"{plugin}/config.json"]
    assert server.env["PLUGIN_HOME"] == str(plugin)


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


@pytest.mark.parametrize(
    "unsafe_name",
    ["../escape", "/tmp/escape", "nested/plugin", r"nested\plugin"],
)
def test_install_rejects_unsafe_manifest_name(tmp_path: Path, unsafe_name: str) -> None:
    src = make_plugin(tmp_path / "src", "source", extra_manifest={"name": unsafe_name})
    target = tmp_path / "installed"

    outcome, message = install_plugin(str(src), target)

    assert outcome == InstallOutcome.FAILED
    assert "Invalid plugin name" in message
    assert not (tmp_path / "escape").exists()
    assert not (target / "nested" / "plugin").exists()


def test_uninstall_removes_dir_and_lock_entry(tmp_path: Path) -> None:
    src = make_plugin(tmp_path / "src")
    target = tmp_path / "installed"
    install_plugin(str(src), target)
    message = uninstall_plugin("demo", target)
    assert "Uninstalled" in message
    assert not (target / "demo").exists()
    assert "demo" not in read_lockfile(target)
    assert uninstall_plugin("demo", target) == "Plugin not found: demo"


@pytest.mark.parametrize("selector", ["../victim", "nested/plugin"])
def test_uninstall_rejects_unsafe_selector(tmp_path: Path, selector: str) -> None:
    target = tmp_path / "installed"
    target.mkdir()
    victim = (
        make_plugin(tmp_path, "victim")
        if selector.startswith("..")
        else make_plugin(target / "nested", "plugin")
    )

    message = uninstall_plugin(selector, target)

    assert message.startswith("Invalid plugin name:")
    assert victim.is_dir()


def test_uninstall_rejects_absolute_selector(tmp_path: Path) -> None:
    target = tmp_path / "installed"
    target.mkdir()
    victim = make_plugin(tmp_path, "victim")

    message = uninstall_plugin(str(victim), target)

    assert message.startswith("Invalid plugin name:")
    assert victim.is_dir()


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


def test_manifest_permissions_do_not_authorize_mcp_calls() -> None:
    from deepseek_tui.tools.approval import (
        needs_mcp_approval_prompt,
        plan_requires_mcp_approval,
    )

    name = "mcp_demo-srv__do_thing"
    # Default: non-read-only MCP tool always requires approval.
    assert plan_requires_mcp_approval(name, "on-request") is True
    # A plugin declaration is only a claim; it cannot bypass approval.
    assert plan_requires_mcp_approval(name, "on-request", ["read_only"]) is True
    assert needs_mcp_approval_prompt(name, "on-request", ["read_only"]) is True
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
    """Plugin commands + agents are indexed at create and activate on demand."""
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
        # Deferred: catalog in index, live maps empty until activation.
        assert "demo" in engine.plugin_index
        assert engine.plugin_index["demo"]["commands"]
        assert engine.plugin_index["demo"]["agents"]
        assert "demo:greet" not in engine.plugin_commands

        # Command expansion activates on demand and substitutes $ARGUMENTS.
        expanded = engine._expand_plugin_command("/demo:greet World")
        assert expanded is not None
        assert "World" in expanded
        assert "$ARGUMENTS" not in expanded
        assert "demo:greet" in engine.plugin_commands
        assert "demo-specialist" in engine.plugin_agents
        assert "demo:demo-specialist" in engine.plugin_agents
        assert "plugin_agents" in engine.tool_context.metadata

        # Non-command messages and unknown commands pass through.
        assert engine._expand_plugin_command("hello there") is None
        assert engine._expand_plugin_command("/demo:missing x") is None

        # Components surface in the system prompt block (qualified agent id).
        block = engine._render_plugin_components_context()
        assert block is not None
        assert "/demo:greet" in block
        assert "demo:demo-specialist" in block or "demo-specialist" in block
    finally:
        await engine.shutdown_session()


def test_plugin_components_context_collapses_past_limit(tmp_path: Path) -> None:
    """Small installs keep per-item listings; large ones use the thin catalog."""
    from deepseek_tui.engine.prompts import (
        render_installed_plugins_catalog,
        render_plugin_components_context,
    )
    from deepseek_tui.integrations.plugins import PluginAgent, PluginCommand
    from types import SimpleNamespace

    def cmd(i: int) -> PluginCommand:
        return PluginCommand(
            name=f"cmd{i}",
            plugin=f"plug{i % 3}",
            description=f"Command number {i} with a long description.",
            body="…",
            path=tmp_path / f"c{i}.md",
        )

    def agent(i: int) -> PluginAgent:
        return PluginAgent(
            name=f"agent{i}",
            plugin=f"plug{i % 3}",
            description=f"Agent number {i} with a long description.",
            body="…",
            path=tmp_path / f"a{i}.md",
        )

    # Under the detailed threshold: full per-item listing with descriptions.
    small = render_plugin_components_context([cmd(1)], [agent(1)], list_limit=10)
    assert "/plug1:cmd1" in small
    assert "Command number 1" in small
    assert "Agent number 1" in small

    # Large surfaces: thin per-plugin catalog (no per-command dump).
    catalog = [
        SimpleNamespace(
            name="plug0",
            description="First pack",
            skills=2,
            commands=10,
            agents=13,
            rules=0,
            mcp=0,
            hooks=0,
        ),
        SimpleNamespace(
            name="plug1",
            description="Second pack",
            skills=0,
            commands=10,
            agents=14,
            rules=1,
            mcp=1,
            hooks=0,
        ),
    ]
    thin = render_installed_plugins_catalog(catalog)
    assert "## Installed Plugins (contributing)" in thin
    assert "plug0: First pack" in thin
    assert "commands:10" in thin
    assert "agents:13" in thin
    assert "/plug0:cmd" not in thin
    assert "`/<plugin>:<command>" in thin


def test_plugin_rules_inactive_hides_non_always_apply() -> None:
    """Unmounted catalog lists only always_apply rules; mount injects all."""
    from deepseek_tui.engine.prompts import render_plugin_rules_context
    from types import SimpleNamespace
    rules = [
        SimpleNamespace(
            plugin="alpha",
            name="core",
            description="always on",
            always_apply=True,
            body="ALWAYS-BODY",
        ),
        SimpleNamespace(
            plugin="alpha",
            name="scenario",
            description="scenario only",
            always_apply=False,
            body="SCENARIO-BODY",
        ),
    ]
    unmounted = render_plugin_rules_context(rules)
    assert "always on" in unmounted
    assert "scenario only" not in unmounted
    assert "SCENARIO-BODY" not in unmounted

    mounted = render_plugin_rules_context(rules, active_plugin="alpha")
    assert "ALWAYS-BODY" in mounted
    assert "SCENARIO-BODY" in mounted


def test_load_marketplace_resolves_root_level_json(tmp_path: Path) -> None:
    """Root-level marketplace.json must resolve sources relative to the repo."""
    from deepseek_tui.integrations.plugins import load_marketplace

    repo = tmp_path / "repo"
    (repo / "plugins").mkdir(parents=True)
    make_plugin(repo / "plugins", "alpha", with_hook=False, with_mcp=False)
    (repo / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "root-market",
                "plugins": [{"name": "alpha", "source": "./plugins/alpha"}],
            }
        ),
        encoding="utf-8",
    )
    entries = load_marketplace(repo)
    assert {e.name for e in entries} == {"alpha"}
    assert entries[0].path.is_dir()


def test_trust_and_uninstall_resolve_manifest_name(tmp_path: Path) -> None:
    """Folder name may differ from manifest name — trust/uninstall still work."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    folder = plugins / "my-fork"
    folder.mkdir()
    (folder / ".deepseek-plugin").mkdir()
    (folder / ".deepseek-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "cool-plugin",
                "version": "1.0.0",
                "mcpServers": {"s": {"command": "true"}},
            }
        ),
        encoding="utf-8",
    )
    assert "Trusted" in set_plugin_trusted("cool-plugin", True, plugins)
    assert read_lockfile(plugins)["cool-plugin"]["trusted"] is True
    assert "Uninstalled" in uninstall_plugin("cool-plugin", plugins)
    assert not folder.exists()
    assert "cool-plugin" not in read_lockfile(plugins)


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
    # Foreign tool names from the persona frontmatter map onto DeepSeek ids.
    assert spawned.allowed_tools is not None
    assert "read_file" in spawned.allowed_tools
    assert "grep_files" in spawned.allowed_tools
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
        wl, _servers = engine._active_plugin_whitelist()
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
        wl, _servers = engine._active_plugin_whitelist()
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

        # Bypass collect_light_contributions's own trust gating: return a server
        # anyway, and stub _server_tool_names, to prove the explicit gate in
        # _active_plugin_whitelist is what blocks the name (not the absence of
        # contributed servers).
        fake_contribs = PluginContributions(
            mcp_servers=[McpServerConfig(name="mcp-plugin-srv", command="cat")]
        )
        monkeypatch.setattr(
            plugin_mod, "collect_light_contributions", lambda *a, **k: fake_contribs
        )
        engine._server_tool_names = lambda server: frozenset(  # type: ignore[assignment]
            {"mcp_mcp-plugin-srv__do"}
        )

        wl, _servers = engine._active_plugin_whitelist()
        assert wl is not None
        assert "mcp_mcp-plugin-srv__do" not in wl  # gate blocked (untrusted)

        # Trust + re-mount -> gate allows the name through.
        set_plugin_trusted("mcp-plugin", True, plugins_dir)
        engine.set_active_plugin("mcp-plugin")
        wl2, servers2 = engine._active_plugin_whitelist()
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
        wl_result = engine._active_plugin_whitelist()
        engine._focus_tool_whitelist = (
            wl_result[0] if wl_result is not None else None
        )
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


def test_discover_does_not_backfill_contribution_index(tmp_path) -> None:
    """Discovery is pure-read: missing indexes are not written to disk."""
    from deepseek_tui.integrations.plugins import LOCKFILE_NAME

    plugins = tmp_path / "plugins"
    make_plugin(plugins, "legacy", with_command=True, with_agent=True)
    lock_path = plugins / LOCKFILE_NAME
    lock_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "legacy": {
                        "source": str(plugins / "legacy"),
                        "version": "1.2.3",
                        "enabled": True,
                        "trusted": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert "contribution_index" not in read_lockfile(plugins)["legacy"]
    found = discover_plugins(plugins_dir=plugins, include_claude=False)
    assert len(found) == 1
    assert found[0].contribution_index is None
    lock = read_lockfile(plugins)["legacy"]
    assert "contribution_index" not in lock


def test_reindex_contribution_indexes(tmp_path) -> None:
    plugins = tmp_path / "plugins"
    make_plugin(plugins, "a", with_command=True)
    make_plugin(plugins, "b", with_agent=True)
    n = reindex_contribution_indexes(plugins, include_claude=False)
    assert n == 2
    lock = read_lockfile(plugins)
    assert "commands" in lock["a"]["contribution_index"]
    assert "agents" in lock["b"]["contribution_index"]


def test_install_message_mentions_next_session(tmp_path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    src = make_plugin(tmp_path / "src", "hooky", with_hook=True, with_mcp=True)
    outcome, message = install_plugin(str(src), plugins, trust=True)
    assert outcome.value == "installed"
    assert "next session" in message.lower()


def test_trust_message_mentions_next_session(tmp_path) -> None:
    plugins = tmp_path / "plugins"
    src = make_plugin(tmp_path / "src", "hooky", with_hook=True)
    install_plugin(str(src), plugins, trust=False)
    msg = set_plugin_trusted("hooky", True, plugins)
    assert "Trusted plugin hooky" in msg
    assert "next session" in msg.lower()


async def test_scenario_isolates_plugin_hooks(tmp_path) -> None:
    """In scenario mode only the active plugin's hooks (+ user hooks) run."""
    from deepseek_tui.config.models import HooksConfig, LifecycleHookEntry
    from deepseek_tui.integrations.hooks import HookExecutor

    cfg = HooksConfig(
        enabled=True,
        hooks=[
            LifecycleHookEntry(
                event="session_start",
                name="alpha:session_start",
                command=f"echo alpha >> {tmp_path / 'out.txt'}",
            ),
            LifecycleHookEntry(
                event="session_start",
                name="beta:session_start",
                command=f"echo beta >> {tmp_path / 'out.txt'}",
            ),
            LifecycleHookEntry(
                event="session_start",
                name="user-hook",
                command=f"echo user >> {tmp_path / 'out.txt'}",
            ),
        ],
    )
    executor = HookExecutor(cfg, tmp_path)
    executor.scenario_plugin = "alpha"
    results = await executor.execute("session_start")
    assert all(r.success for r in results)
    text = (tmp_path / "out.txt").read_text(encoding="utf-8")
    assert "alpha" in text
    assert "user" in text
    assert "beta" not in text
    assert executor.has_hooks_for_event("session_start")


async def test_agent_spawn_resolves_qualified_plugin_persona(tmp_path) -> None:
    """``plugin:persona`` resolves; bare name still works when unique."""
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
    )
    registry = {
        "demo:demo-specialist": persona,
        "demo-specialist": persona,
    }
    manager = SubAgentManager(workspace=tmp_path)
    context = ToolContext(
        working_directory=tmp_path,
        subagent_manager=manager,
        metadata={"plugin_agents": registry},
    )
    tool = AgentSpawnTool()
    result = await tool.execute(
        {"prompt": "do the thing", "type": "demo:demo-specialist"}, context
    )
    assert result.success
    result2 = await tool.execute(
        {"prompt": "again", "type": "demo-specialist"}, context
    )
    assert result2.success
    await manager.shutdown()


async def test_set_active_plugin_scenario_copy_and_hook_filter(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins = tmp_path / "home" / "plugins"
    make_plugin(plugins, "scene", with_command=True, with_hook=False)
    from unittest.mock import AsyncMock

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
        note = engine.set_active_plugin("scene")
        assert "已进入场景" in note
        assert engine.hook_executor.scenario_plugin == "scene"
        off = engine.set_active_plugin("off")
        assert "已退出场景" in off
        assert engine.hook_executor.scenario_plugin is None
        # Mid-session discovery tip when name was not present at create.
        engine._session_plugin_names.clear()
        tip = engine.set_active_plugin("scene")
        assert "新开会话" in tip
    finally:
        await engine.shutdown_session()


async def test_untrusted_plugin_skill_allowed_tools_ignored_in_whitelist(
    tmp_path, monkeypatch
) -> None:
    """Untrusted mounts must not expand the whitelist via skill allowed-tools."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    plugins_dir = tmp_path / "home" / "plugins"
    plugin = make_plugin(
        plugins_dir,
        "expand",
        with_hook=False,
        with_mcp=False,
        with_skill=True,
    )
    skill = plugin / "skills" / "demo-skill" / "SKILL.md"
    skill.write_text(
        "---\nname: demo-skill\ndescription: d\n"
        "allowed-tools: write_file, exec_shell\n---\n\nBody.\n",
        encoding="utf-8",
    )

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.engine.orchestrator.helpers import FOCUS_READ_BASE

    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    engine = await Engine.create(
        EngineHandle(), AsyncMock(), config=cfg, working_directory=workspace
    )
    try:
        assert not engine._loaded_plugins[0].trusted
        engine.set_active_plugin("expand")
        wl, _servers = engine._active_plugin_whitelist()
        assert wl is not None
        assert wl <= FOCUS_READ_BASE or wl == FOCUS_READ_BASE
        assert "write_file" not in wl
        assert "bash" not in wl and "exec_shell" not in wl
    finally:
        await engine.shutdown_session()


async def test_agent_spawn_untrusted_plugin_confined_to_read_base(
    tmp_path,
) -> None:
    from deepseek_tui.engine.orchestrator.helpers import FOCUS_READ_BASE
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
        tools=("Read", "Bash"),
    )
    manager = SubAgentManager(workspace=tmp_path)
    context = ToolContext(
        working_directory=tmp_path,
        subagent_manager=manager,
        metadata={
            "plugin_agents": {"demo-specialist": persona},
            "plugin_trust": {"demo": False},
        },
    )
    result = await AgentSpawnTool().execute(
        {"prompt": "do the thing", "type": "demo-specialist"}, context
    )
    assert result.success
    spawned = manager._agents[result.metadata["agent_id"]]
    assert spawned.allowed_tools is not None
    assert set(spawned.allowed_tools) == set(FOCUS_READ_BASE)
    await manager.shutdown()