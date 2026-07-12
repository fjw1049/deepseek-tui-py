"""Plugin system — packaging layer over skills / hooks / MCP.

A plugin is a directory with a ``plugin.json`` manifest that bundles
multiple component types into one installable, versionable, trustable
unit:

* ``skills``      — directories of SKILL.md skills (always loaded)
* ``hooks``       — lifecycle hook entries (loaded only when trusted)
* ``mcpServers``  — MCP server configs (loaded only when trusted)

Manifest locations (first match wins)::

    <plugin>/.deepseek-plugin/plugin.json
    <plugin>/.claude-plugin/plugin.json      (Claude Code compat)
    <plugin>/plugin.json

Field names follow the Claude Code plugin manifest so existing
community plugins can be dropped in. Per that spec the manifest itself
is *optional*: mainstream plugins ship minimal manifests (or none) and
expose components as on-disk conventions, so ``skills`` / ``commands`` /
``agents`` / ``rules`` are auto-discovered from the matching root
directories, ``hooks`` from ``./hooks/hooks.json`` and ``mcpServers``
from ``./.mcp.json`` when the manifest omits the key or is absent.
Like skills, ``commands`` and ``agents`` are declarative text (prompt
templates and persona system prompts) and always load; only executable
components (``hooks`` / ``mcpServers``) stay gated behind trust.
Component types we do not wire yet (``outputStyles``, ``lspServers``)
are surfaced as warnings, not errors.

Scopes:

* project — ``<workspace>/.deepseek/plugins/`` (wins on name conflict)
* user    — ``~/.deepseek/plugins/``

Each scope directory carries an ``installed_plugins.json`` lockfile
recording source / version / enabled / trusted per plugin. Plugins
present on disk but absent from the lockfile (dev checkouts) are
discovered as enabled + untrusted.

Trust model: skills are declarative text and always load, matching the
existing skills system. Hooks (arbitrary shell) and MCP servers
(arbitrary processes) only load from trusted plugins.

``${PLUGIN_DIR}`` in hook commands and MCP command/args/env expands to
the plugin root, so plugins can ship scripts and reference them
portably.

Extras layered on top of the core model:

* ``permissions`` in the manifest (e.g. ``["read", "network"]``) map to
  :class:`~deepseek_tui.tools.registry.ToolCapability` at approval time
  so a plugin that declares itself read-only doesn't trigger the blanket
  "MCP action requires approval" prompt.
* Plugin MCP servers default to **lazy** startup — they are excluded
  from eager ``start_all`` at app launch and only spawn on first tool
  call / discovery.
* ``~/.claude/plugins`` (Claude Code installs) is scanned read-only as a
  third scope; enable/trust state for those lives in the user lockfile.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import LifecycleHookEntry
from deepseek_tui.integrations.hooks import LIFECYCLE_EVENTS
from deepseek_tui.integrations.plugin_compat import (
    matcher_to_condition,
    normalize_installed_plugin,
)
from deepseek_tui.integrations.skills import (
    GITHUB_ALLOWED_HOSTS,
    REGISTRY_ALLOWED_HOSTS,
    InstallOutcome,
    InstallSource,
    Skill,
    SkillRegistry,
    _DownloadMissing,
    _DownloadTooLarge,
    _extract_tarball,
    _github_archive_urls,
    _host_is_allowed,
    _parse_skill_file,
    _stream_download,
)
from deepseek_tui.mcp.config import McpServerConfig, load_mcp_config, servers_from_document

__all__ = [
    "DEFAULT_PLUGIN_REGISTRY_URL",
    "LOCKFILE_NAME",
    "MARKETPLACES_REGISTRY_NAME",
    "PLUGIN_MANIFEST_CANDIDATES",
    "LoadedPlugin",
    "MarketplaceEntry",
    "PluginAgent",
    "PluginCommand",
    "PluginContributions",
    "PluginManifest",
    "PluginRegistryDocument",
    "PluginRule",
    "PluginRegistryEntry",
    "add_marketplace",
    "capability_values_from_permissions",
    "claude_plugins_dir",
    "collect_contributions",
    "discover_claude_plugins",
    "discover_plugins",
    "fetch_plugin_registry",
    "install_plugin",
    "load_marketplace",
    "load_plugin_manifest",
    "marketplaces_dir",
    "merge_plugin_skills",
    "parse_plugin_at_marketplace",
    "plugins_directories",
    "project_plugins_dir",
    "read_lockfile",
    "read_marketplaces",
    "remove_marketplace",
    "resolve_marketplace_plugin",
    "scaffold_plugin",
    "set_plugin_enabled",
    "set_plugin_trusted",
    "uninstall_plugin",
    "update_marketplace",
    "update_plugin",
    "user_plugins_dir",
]

_LOG = logging.getLogger(__name__)

LOCKFILE_NAME = "installed_plugins.json"

PLUGIN_MANIFEST_CANDIDATES = (
    Path(".deepseek-plugin") / "plugin.json",
    Path(".claude-plugin") / "plugin.json",
    Path(".codebuddy-plugin") / "plugin.json",
    Path("plugin.json"),
)

# Component manifest keys we accept but do not wire yet.
_UNSUPPORTED_COMPONENT_KEYS = ("outputStyles", "lspServers")

# Auto-discovery defaults: mainstream (Claude Code) plugins omit these
# manifest keys and lay the components out as directories at the plugin
# root. When the key is absent but the directory holds the expected
# files, we assume the conventional relative path.
_DEFAULT_SKILLS_PATH = "./skills"
_DEFAULT_COMMANDS_PATH = "./commands"
_DEFAULT_AGENTS_PATH = "./agents"
_DEFAULT_RULES_PATH = "./rules"
_DEFAULT_HOOKS_PATH = "./hooks/hooks.json"
_DEFAULT_MCP_PATH = "./.mcp.json"

# Manifest ``permissions`` values → ToolCapability values. Consumed at
# approval time for the plugin's MCP tools (see ``tools/approval.py``).
_PERMISSION_CAPABILITY_MAP = {
    "read": "read_only",
    "read-only": "read_only",
    "read_only": "read_only",
    "write": "writes_files",
    "writes_files": "writes_files",
    "filesystem": "writes_files",
    "exec": "executes_code",
    "execute": "executes_code",
    "shell": "executes_code",
    "executes_code": "executes_code",
    "network": "network",
    "net": "network",
}

DEFAULT_PLUGIN_REGISTRY_URL = (
    "https://raw.githubusercontent.com/deepseek-ai/"
    "DeepSeek-TUI/main/plugins-registry/index.json"
)

# Plugins bundle more than a single skill; allow a larger archive than
# the 5 MiB skill cap but keep the gzip-bomb guard meaningful.
PLUGIN_MAX_SIZE_BYTES = 20 * 1024 * 1024

_PLUGIN_DIR_TOKEN = "${PLUGIN_DIR}"


# ── Paths ────────────────────────────────────────────────────────────────


def user_plugins_dir() -> Path:
    """``~/.deepseek/plugins/`` — cross-project user plugins."""
    from deepseek_tui.config.paths import user_deepseek_dir

    return user_deepseek_dir() / "plugins"


def project_plugins_dir(workspace: Path | None = None) -> Path:
    """``<workspace>/.deepseek/plugins/`` — checkout-scoped plugins."""
    from deepseek_tui.config.paths import project_deepseek_dir

    return project_deepseek_dir(workspace) / "plugins"


def claude_plugins_dir() -> Path:
    """``~/.claude/plugins/`` — Claude Code installs, scanned read-only."""
    override = os.getenv("CLAUDE_PLUGINS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "plugins"


def plugins_directories(
    plugins_dir: Path | None = None,
    workspace: Path | None = None,
) -> list[Path]:
    """Ordered plugin scope directories (first wins on name conflicts).

    1. Explicit override (tests, CLI flag)
    2. ``<workspace>/.deepseek/plugins`` — project scope
    3. ``~/.deepseek/plugins`` — user scope
    """
    dirs: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path | None) -> None:
        if p is None:
            return
        try:
            canonical = p.resolve()
        except OSError:
            return
        if canonical.is_dir() and canonical not in seen:
            dirs.append(p)
            seen.add(canonical)

    if plugins_dir is not None:
        _add(plugins_dir)
    if workspace:
        _add(project_plugins_dir(workspace))
    if plugins_dir is None:
        _add(user_plugins_dir())
    return dirs


# ── Manifest ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Parsed plugin.json."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    skills: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    hooks: tuple[Any, ...] = ()
    mcp_servers: Any = None
    unsupported: tuple[str, ...] = ()
    # Declared permission strings, normalized lowercase (manifest key
    # ``permissions``). Advisory: consumed by the approval layer for the
    # plugin's MCP tools and surfaced in CLI/UI trust flows.
    permissions: tuple[str, ...] = ()


def capability_values_from_permissions(
    permissions: tuple[str, ...] | list[str],
) -> list[str]:
    """Map declared permission strings to ``ToolCapability`` values.

    Unknown permission strings are dropped (they still show verbatim in
    CLI/UI). Returns an empty list when nothing maps — callers treat
    that as "no declaration" and fall back to the conservative default.
    """
    out: list[str] = []
    for perm in permissions:
        cap = _PERMISSION_CAPABILITY_MAP.get(perm.strip().lower())
        if cap and cap not in out:
            out.append(cap)
    return out


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(v for v in value if isinstance(v, str))
    return ()


def _skills_dir_has_skills(plugin_dir: Path) -> bool:
    """True when ``skills/<name>/SKILL.md`` exists under the plugin root."""
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return False
    try:
        for child in skills_dir.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                return True
    except OSError:
        return False
    return False


def _dir_has_markdown(plugin_dir: Path, subdir: str) -> bool:
    """True when ``<subdir>/*.md`` exists under the plugin root.

    Used to auto-discover ``commands/`` and ``agents/`` directories laid
    out per the Claude Code convention when the manifest omits the key.
    """
    target = plugin_dir / subdir
    if not target.is_dir():
        return False
    try:
        return any(
            child.is_file() and child.suffix == ".md"
            for child in target.iterdir()
        )
    except OSError:
        return False


def _synthesize_single_skill_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Treat a manifest-less folder whose root holds ``SKILL.md`` as a plugin.

    Mainstream ecosystems ship standalone skills this way (CodeBuddy/WorkBuddy
    ``pptx-generator``, ``ardot-slides``): a folder with a top-level ``SKILL.md``
    and no ``plugin.json``. We synthesize a single-skill manifest so it installs
    and loads like any other plugin. ``skills=(".",)`` points ``_collect_skills``
    at the plugin dir itself, which is a leaf skill dir.
    """
    leaf = plugin_dir / "SKILL.md"
    if not leaf.is_file():
        return None
    name = plugin_dir.name
    description = ""
    try:
        meta, _ = _parse_md_frontmatter(leaf)
        name = (meta.get("name") or "").strip() or plugin_dir.name
        description = meta.get("description", "")
    except OSError:
        pass
    return PluginManifest(name=name, description=description, skills=(".",))


def _default_hooks(plugin_dir: Path) -> tuple[str, ...]:
    """``("./hooks/hooks.json",)`` when the conventional file exists."""
    if (plugin_dir / "hooks" / "hooks.json").is_file():
        return (_DEFAULT_HOOKS_PATH,)
    return ()


def _default_mcp(plugin_dir: Path) -> str | None:
    """``"./.mcp.json"`` when the conventional file exists at the root."""
    if (plugin_dir / ".mcp.json").is_file():
        return _DEFAULT_MCP_PATH
    return None


def _synthesize_layout_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Treat a manifest-less folder with conventional component dirs as a plugin.

    Per the Claude Code spec the manifest is *optional*: components are
    auto-discovered from the directory layout (``skills/`` / ``commands/`` /
    ``agents/`` / ``rules/`` / ``hooks/hooks.json`` / ``.mcp.json``). Returns
    ``None`` when the folder holds none of them (i.e. it is not a plugin).
    """
    skills = (_DEFAULT_SKILLS_PATH,) if _skills_dir_has_skills(plugin_dir) else ()
    commands = (
        (_DEFAULT_COMMANDS_PATH,) if _dir_has_markdown(plugin_dir, "commands") else ()
    )
    agents = (
        (_DEFAULT_AGENTS_PATH,) if _dir_has_markdown(plugin_dir, "agents") else ()
    )
    rules = (_DEFAULT_RULES_PATH,) if _dir_has_markdown(plugin_dir, "rules") else ()
    hooks = _default_hooks(plugin_dir)
    mcp = _default_mcp(plugin_dir)
    if not (skills or commands or agents or rules or hooks) and mcp is None:
        return None
    return PluginManifest(
        name=plugin_dir.name,
        skills=skills,
        commands=commands,
        agents=agents,
        rules=rules,
        hooks=hooks,
        mcp_servers=mcp,
    )


def load_plugin_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Load and parse the plugin manifest, or ``None`` when absent/invalid."""
    manifest_path: Path | None = None
    for candidate in PLUGIN_MANIFEST_CANDIDATES:
        p = plugin_dir / candidate
        if p.is_file():
            manifest_path = p
            break
    if manifest_path is None:
        single = _synthesize_single_skill_manifest(plugin_dir)
        if single is not None:
            return single
        return _synthesize_layout_manifest(plugin_dir)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("failed to parse plugin manifest %s: %s", manifest_path, exc)
        return None
    if not isinstance(data, dict):
        return None

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        name = plugin_dir.name

    hooks_raw = data.get("hooks")
    if isinstance(hooks_raw, (str, dict)):
        hooks: tuple[Any, ...] = (hooks_raw,)
    elif isinstance(hooks_raw, list):
        hooks = tuple(hooks_raw)
    else:
        # Claude Code convention: hooks/hooks.json is the default location
        # when the manifest omits the key.
        hooks = _default_hooks(plugin_dir)

    unsupported = tuple(k for k in _UNSUPPORTED_COMPONENT_KEYS if data.get(k))

    # Mainstream plugins omit these keys and lay components out on disk;
    # assume the conventional relative dir when present (Claude Code compat).
    skills = _as_str_tuple(data.get("skills"))
    if not skills and _skills_dir_has_skills(plugin_dir):
        skills = (_DEFAULT_SKILLS_PATH,)
    commands = _as_str_tuple(data.get("commands"))
    if not commands and _dir_has_markdown(plugin_dir, "commands"):
        commands = (_DEFAULT_COMMANDS_PATH,)
    agents = _as_str_tuple(data.get("agents"))
    if not agents and _dir_has_markdown(plugin_dir, "agents"):
        agents = (_DEFAULT_AGENTS_PATH,)
    rules = _as_str_tuple(data.get("rules"))
    if not rules and _dir_has_markdown(plugin_dir, "rules"):
        rules = (_DEFAULT_RULES_PATH,)
    mcp_servers = data.get("mcpServers", data.get("mcp_servers"))
    if mcp_servers is None:
        # Claude Code convention: .mcp.json at the plugin root is the
        # default location when the manifest omits the key.
        mcp_servers = _default_mcp(plugin_dir)

    return PluginManifest(
        name=name.strip(),
        version=str(data.get("version") or "0.0.0"),
        description=str(data.get("description") or ""),
        skills=skills,
        commands=commands,
        agents=agents,
        rules=rules,
        hooks=hooks,
        mcp_servers=mcp_servers,
        unsupported=unsupported,
        permissions=tuple(
            p.strip().lower() for p in _as_str_tuple(data.get("permissions"))
            if p.strip()
        ),
    )


# ── Lockfile ─────────────────────────────────────────────────────────────


def _lockfile_path(plugins_dir: Path) -> Path:
    return plugins_dir / LOCKFILE_NAME


def read_lockfile(plugins_dir: Path) -> dict[str, dict[str, Any]]:
    """Read the scope lockfile. Missing/corrupt → empty mapping."""
    path = _lockfile_path(plugins_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("failed to read plugin lockfile %s: %s", path, exc)
        return {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return {}
    return {k: v for k, v in plugins.items() if isinstance(v, dict)}


def _write_lockfile(plugins_dir: Path, plugins: dict[str, dict[str, Any]]) -> None:
    from deepseek_tui.utils import write_json_atomic

    write_json_atomic(_lockfile_path(plugins_dir), {"version": 1, "plugins": plugins})


def _update_lockfile_entry(
    plugins_dir: Path, name: str, **fields: Any
) -> dict[str, Any]:
    plugins = read_lockfile(plugins_dir)
    entry = plugins.get(name, {})
    entry.update(fields)
    plugins[name] = entry
    _write_lockfile(plugins_dir, plugins)
    return entry


# ── Discovery ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    """A discovered plugin with resolved lockfile state."""

    manifest: PluginManifest
    path: Path
    scope: str  # "project" | "user" | "override"
    enabled: bool
    trusted: bool

    @property
    def name(self) -> str:
        return self.manifest.name


def _scope_for(plugins_dir: Path, workspace: Path | None, override: Path | None) -> str:
    if override is not None and plugins_dir == override:
        return "override"
    if workspace is not None:
        try:
            if plugins_dir.resolve() == project_plugins_dir(workspace).resolve():
                return "project"
        except OSError:
            pass
    return "user"


def discover_plugins(
    plugins_dir: Path | None = None,
    workspace: Path | None = None,
    *,
    include_disabled: bool = False,
    include_claude: bool = True,
) -> list[LoadedPlugin]:
    """Discover plugins across scope directories.

    First scope wins on name conflicts (project overrides user, both
    override Claude Code installs). Disabled plugins are skipped unless
    ``include_disabled`` is set.
    """
    found: list[LoadedPlugin] = []
    seen_names: set[str] = set()

    def _add(
        manifest: PluginManifest,
        path: Path,
        scope: str,
        entry: dict[str, Any],
    ) -> None:
        key = manifest.name.lower()
        if key in seen_names:
            return
        seen_names.add(key)
        enabled = bool(entry.get("enabled", True))
        trusted = bool(entry.get("trusted", False))
        if not enabled and not include_disabled:
            return
        found.append(
            LoadedPlugin(
                manifest=manifest,
                path=path,
                scope=scope,
                enabled=enabled,
                trusted=trusted,
            )
        )

    for scope_dir in plugins_directories(plugins_dir, workspace):
        lock = read_lockfile(scope_dir)
        scope = _scope_for(scope_dir, workspace, plugins_dir)
        for child in sorted(scope_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            manifest = load_plugin_manifest(child)
            if manifest is None:
                continue
            _add(manifest, child, scope, lock.get(manifest.name, {}))

    # Claude Code interop: plugins installed via Claude Code are surfaced
    # read-only. Their enable/trust state lives in *our* user lockfile so
    # we never write into ~/.claude.
    if include_claude and plugins_dir is None:
        user_lock = read_lockfile(user_plugins_dir())
        for manifest, path in discover_claude_plugins():
            _add(manifest, path, "claude", user_lock.get(manifest.name, {}))
    return found


def discover_claude_plugins(
    root: Path | None = None,
) -> list[tuple[PluginManifest, Path]]:
    """Scan ``~/.claude/plugins`` for plugin directories (read-only).

    Prefers Claude Code's own ``installed_plugins.json`` (its records
    carry explicit ``installPath`` values, e.g.
    ``cache/<marketplace>/<plugin>/<version>``). Falls back to a bounded
    directory walk for older/unknown layouts.
    """
    base = root or claude_plugins_dir()
    if not base.is_dir():
        return []
    out: list[tuple[PluginManifest, Path]] = []
    seen_paths: set[Path] = set()

    def _try(path: Path) -> None:
        if path in seen_paths:
            return
        seen_paths.add(path)
        if not path.is_dir():
            return
        manifest = load_plugin_manifest(path)
        if manifest is not None:
            out.append((manifest, path))

    lock = base / "installed_plugins.json"
    if lock.is_file():
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _LOG.warning("failed to read Claude plugin lockfile %s: %s", lock, exc)
            data = None
        table = data.get("plugins") if isinstance(data, dict) else None
        if isinstance(table, dict):
            for records in table.values():
                # v1 stores a single record object; v2+ a list per plugin.
                items = records if isinstance(records, list) else [records]
                for rec in items:
                    if not isinstance(rec, dict):
                        continue
                    raw = rec.get("installPath") or rec.get("install_path")
                    if isinstance(raw, str) and raw:
                        _try(Path(raw).expanduser())
    if out:
        return out

    # Fallback: bounded walk covering cache/<mp>/<plugin>/<version> and
    # flatter legacy layouts; stops descending once a manifest is found.
    def _walk(directory: Path, depth: int) -> None:
        try:
            children = sorted(directory.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            manifest = load_plugin_manifest(child)
            if manifest is not None:
                out.append((manifest, child))
            elif depth < 4:
                _walk(child, depth + 1)

    _walk(base, 1)
    return out


# ── Contributions ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PluginCommand:
    """A prompt command contributed by a plugin (``commands/<stem>.md``).

    Invoked as ``/<plugin>:<command>``. ``body`` is a prompt template
    expanded (``$ARGUMENTS`` substitution) and sent as the user message.
    """

    name: str  # invocation stem, e.g. "python-scaffold"
    plugin: str  # owning plugin name
    description: str
    body: str
    path: Path
    argument_hint: str = ""

    @property
    def qualified(self) -> str:
        """Namespaced invocation name, e.g. ``python-development:python-scaffold``."""
        return f"{self.plugin}:{self.name}"


@dataclass(frozen=True, slots=True)
class PluginAgent:
    """A persona contributed by a plugin (``agents/<stem>.md``).

    Spawnable as a sub-agent whose system prompt is ``body``. ``model`` and
    ``tools`` mirror the Claude Code agent frontmatter; they are advisory
    (recorded for display / doctor) — foreign model IDs and cross-ecosystem
    tool names are not forced onto the DeepSeek runtime so the persona always
    runs. When ``tools`` is empty the sub-agent gets the full registry.
    """

    name: str  # frontmatter name, e.g. "unit-testing-test-automator"
    plugin: str
    description: str
    body: str
    path: Path
    model: str = ""
    tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginRule:
    """An always-on instruction contributed by a plugin (``rules/<stem>.md``).

    CodeBuddy plugins carry their core behavior in ``rules`` — system-level
    directives (``alwaysApply: true``) injected into the system prompt.
    Declarative text (no execution), so it loads without trust, mirroring the
    project-context / skills injection model. ``enabled: false`` opts out.
    """

    name: str
    plugin: str
    description: str
    body: str
    path: Path
    always_apply: bool = True


@dataclass(slots=True)
class PluginContributions:
    """Aggregated components from all enabled plugins."""

    skills: list[Skill] = field(default_factory=list)
    commands: list[PluginCommand] = field(default_factory=list)
    agents: list[PluginAgent] = field(default_factory=list)
    rules: list[PluginRule] = field(default_factory=list)
    hook_entries: list[LifecycleHookEntry] = field(default_factory=list)
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _substitute(value: str, plugin_dir: Path) -> str:
    return value.replace(_PLUGIN_DIR_TOKEN, str(plugin_dir))


_MD_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_md_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    """Parse a Markdown file's YAML-ish frontmatter into ``(meta, body)``.

    Tolerant of files without frontmatter (mainstream plugins ship some
    commands with a bare body): returns ``({}, full_text)`` in that case.
    Only simple ``key: value`` scalar lines are read — enough for the
    ``name`` / ``description`` / ``model`` / ``argument-hint`` / ``tools``
    keys these components use.
    """
    content = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = content
    match = _MD_FRONTMATTER_RE.match(content)
    if match:
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()
        body = content[match.end():]
    return meta, body.strip()


def _plugin_child_dir(plugin: LoadedPlugin, rel: str) -> Path | None:
    """Resolve ``rel`` under the plugin dir, rejecting path escapes."""
    resolved = (plugin.path / rel).resolve()
    try:
        resolved.relative_to(plugin.path.resolve())
    except ValueError:
        return None
    return resolved


def _resolve_markdown_targets(
    plugin: LoadedPlugin, rel: str, out: PluginContributions, kind: str
) -> list[Path]:
    """Resolve a manifest component entry to a list of ``*.md`` files.

    A manifest entry may point at either an individual ``.md`` file
    (CodeBuddy convention, e.g. ``./agents/research-subagent.md``) or a
    directory to glob (Claude Code / agents-main convention, e.g.
    ``./commands``). Path escapes are rejected with a warning.
    """
    resolved = _plugin_child_dir(plugin, rel)
    if resolved is None:
        out.warnings.append(
            f"plugin {plugin.name}: {kind} path escapes plugin dir: {rel}"
        )
        return []
    if resolved.is_file() and resolved.suffix == ".md":
        return [resolved]
    if resolved.is_dir():
        return sorted(resolved.glob("*.md"))
    return []


def _collect_commands(plugin: LoadedPlugin, out: PluginContributions) -> None:
    seen = {c.qualified for c in out.commands}
    for rel in plugin.manifest.commands:
        for md in _resolve_markdown_targets(plugin, rel, out, "commands"):
            try:
                meta, body = _parse_md_frontmatter(md)
            except OSError as exc:
                out.warnings.append(
                    f"plugin {plugin.name}: failed to read command {md.name}: {exc}"
                )
                continue
            command = PluginCommand(
                name=md.stem,
                plugin=plugin.name,
                description=meta.get("description", ""),
                body=body,
                path=md,
                argument_hint=meta.get("argument-hint", ""),
            )
            if command.qualified in seen:
                continue
            out.commands.append(command)
            seen.add(command.qualified)


def _collect_agents(plugin: LoadedPlugin, out: PluginContributions) -> None:
    seen = {a.name.lower() for a in out.agents}
    for rel in plugin.manifest.agents:
        for md in _resolve_markdown_targets(plugin, rel, out, "agents"):
            try:
                meta, body = _parse_md_frontmatter(md)
            except OSError as exc:
                out.warnings.append(
                    f"plugin {plugin.name}: failed to read agent {md.name}: {exc}"
                )
                continue
            name = meta.get("name") or md.stem
            if name.lower() in seen:
                continue
            tools_raw = meta.get("tools", "")
            tools = tuple(
                t.strip().strip("[]'\"")
                for t in tools_raw.split(",")
                if t.strip().strip("[]'\"")
            )
            out.agents.append(
                PluginAgent(
                    name=name,
                    plugin=plugin.name,
                    description=meta.get("description", ""),
                    body=body,
                    path=md,
                    model=meta.get("model", ""),
                    tools=tools,
                )
            )
            seen.add(name.lower())


def _collect_rules(plugin: LoadedPlugin, out: PluginContributions) -> None:
    seen = {(r.plugin, r.name) for r in out.rules}
    for rel in plugin.manifest.rules:
        for md in _resolve_markdown_targets(plugin, rel, out, "rules"):
            try:
                meta, body = _parse_md_frontmatter(md)
            except OSError as exc:
                out.warnings.append(
                    f"plugin {plugin.name}: failed to read rule {md.name}: {exc}"
                )
                continue
            if meta.get("enabled", "true").strip().lower() == "false":
                continue
            key = (plugin.name, md.stem)
            if key in seen:
                continue
            always = meta.get("alwaysapply", "true").strip().lower() != "false"
            out.rules.append(
                PluginRule(
                    name=md.stem,
                    plugin=plugin.name,
                    description=meta.get("description", ""),
                    body=body,
                    path=md,
                    always_apply=always,
                )
            )
            seen.add(key)


def collect_contributions(plugins: list[LoadedPlugin]) -> PluginContributions:
    """Fan a plugin list out into per-subsystem contribution lists.

    Skills / commands / agents are declarative text and always load.
    Hooks / MCP servers require ``trusted``.
    """
    out = PluginContributions()
    for plugin in plugins:
        _collect_skills(plugin, out)
        _collect_commands(plugin, out)
        _collect_agents(plugin, out)
        _collect_rules(plugin, out)
        if plugin.manifest.unsupported:
            out.warnings.append(
                f"plugin {plugin.name}: unsupported components ignored: "
                + ", ".join(plugin.manifest.unsupported)
            )
        has_executable = bool(plugin.manifest.hooks) or plugin.manifest.mcp_servers
        if has_executable and not plugin.trusted:
            out.warnings.append(
                f"plugin {plugin.name}: hooks/MCP servers skipped (not trusted; "
                f"run `deepseek-tui plugin trust {plugin.name}`)"
            )
            continue
        if plugin.trusted:
            _collect_hooks(plugin, out)
            _collect_mcp(plugin, out)
    return out


def _collect_skills(plugin: LoadedPlugin, out: PluginContributions) -> None:
    seen = {s.name.lower() for s in out.skills}

    def _add(skill: Skill) -> None:
        if skill.name.lower() not in seen:
            out.skills.append(skill)
            seen.add(skill.name.lower())

    for rel in plugin.manifest.skills:
        skills_dir = _plugin_child_dir(plugin, rel)
        if skills_dir is None:
            out.warnings.append(
                f"plugin {plugin.name}: skills path escapes plugin dir: {rel}"
            )
            continue
        if not skills_dir.is_dir():
            continue
        # Leaf skill dir — SKILL.md directly inside (CodeBuddy declares each
        # skill's own dir, e.g. ``./skills/comps-analysis``).
        leaf = skills_dir / "SKILL.md"
        if leaf.is_file():
            try:
                _add(_parse_skill_file(leaf))
            except Exception as exc:  # noqa: BLE001 — one bad skill must not
                # abort the rest of the plugin's contributions.
                out.warnings.append(
                    f"plugin {plugin.name}: failed to parse {leaf}: {exc}"
                )
            continue
        # Container dir — ``<name>/SKILL.md`` (Claude Code / agents-main).
        reg = SkillRegistry.discover(skills_dir)
        for skill in reg.skills:
            _add(skill)
        out.warnings.extend(reg.warnings)


# CamelCase lifecycle events used by Claude Code / CodeBuddy hooks.json,
# mapped to our snake_case ``LIFECYCLE_EVENTS``. Events without a runtime
# equivalent (Stop, SubagentStop, Notification, PreCompact) are skipped.
_FOREIGN_HOOK_EVENT_MAP = {
    "sessionstart": "session_start",
    "sessionend": "session_end",
    "userpromptsubmit": "message_submit",
    "pretooluse": "tool_call_before",
    "posttooluse": "tool_call_after",
}


def _substitute_hook_command(command: str, plugin_dir: Path) -> str:
    """Resolve plugin-root / project-dir tokens across ecosystems.

    ``${PLUGIN_DIR}`` (native), ``${CODEBUDDY_PLUGIN_ROOT}`` and
    ``${CLAUDE_PLUGIN_ROOT}`` resolve to the plugin's absolute path at load
    time. Project-dir tokens become ``${DEEPSEEK_WORKSPACE}`` — the env var the
    hook runner exports at execution time (shell-expanded in the subprocess).
    """
    command = _substitute(command, plugin_dir)
    root = str(plugin_dir)
    for token in ("${CODEBUDDY_PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}"):
        command = command.replace(token, root)
    for token in ("${CODEBUDDY_PROJECT_DIR}", "${CLAUDE_PROJECT_DIR}"):
        command = command.replace(token, "${DEEPSEEK_WORKSPACE}")
    return command


def _append_native_hook(
    plugin: LoadedPlugin, raw_entry: dict[str, Any], out: PluginContributions
) -> None:
    event = raw_entry.get("event")
    command = raw_entry.get("command")
    if event not in LIFECYCLE_EVENTS or not isinstance(command, str):
        out.warnings.append(
            f"plugin {plugin.name}: invalid hook entry skipped (event={event!r})"
        )
        return
    out.hook_entries.append(
        LifecycleHookEntry(
            event=event,
            command=_substitute_hook_command(command, plugin.path),
            condition=raw_entry.get("condition"),
            timeout_secs=float(raw_entry.get("timeout_secs", 30.0)),
            background=bool(raw_entry.get("background", False)),
            continue_on_error=bool(raw_entry.get("continue_on_error", True)),
            name=f"{plugin.name}:{raw_entry.get('name') or event}",
        )
    )


def _append_foreign_hooks(
    plugin: LoadedPlugin, event_dict: dict[str, Any], out: PluginContributions
) -> None:
    """Parse the Claude Code / CodeBuddy ``{EventName: [group, ...]}`` schema.

    Each group is ``{matcher?, hooks: [{type: command, command, timeout}]}``.
    ``timeout`` is milliseconds. ``matcher`` (a tool-name pattern) is recorded
    as an advisory ``tool_name`` condition for tool events.
    """
    for event_name, groups in event_dict.items():
        mapped = _FOREIGN_HOOK_EVENT_MAP.get(str(event_name).lower())
        if mapped is None:
            out.warnings.append(
                f"plugin {plugin.name}: unsupported hook event "
                f"{event_name!r} skipped"
            )
            continue
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            matcher = group.get("matcher")
            condition = None
            if matcher and mapped in ("tool_call_before", "tool_call_after"):
                # Map the foreign tool-name matcher to our taxonomy so the hook
                # actually fires (e.g. ``Edit|Write`` → edit_file/write_file).
                condition = matcher_to_condition(matcher)
            specs = group.get("hooks", [])
            if not isinstance(specs, list):
                continue
            for spec in specs:
                if not isinstance(spec, dict):
                    continue
                command = spec.get("command")
                if not isinstance(command, str):
                    continue
                if spec.get("type", "command") != "command":
                    out.warnings.append(
                        f"plugin {plugin.name}: unsupported hook type "
                        f"{spec.get('type')!r} skipped"
                    )
                    continue
                timeout = spec.get("timeout")
                timeout_secs = (
                    float(timeout) / 1000.0
                    if isinstance(timeout, (int, float))
                    else 30.0
                )
                out.hook_entries.append(
                    LifecycleHookEntry(
                        event=mapped,
                        command=_substitute_hook_command(command, plugin.path),
                        condition=condition,
                        timeout_secs=timeout_secs,
                        background=False,
                        continue_on_error=True,
                        name=f"{plugin.name}:{event_name}",
                    )
                )


def _collect_hooks(plugin: LoadedPlugin, out: PluginContributions) -> None:
    for item in plugin.manifest.hooks:
        if isinstance(item, str):
            hook_path = _plugin_child_dir(plugin, item)
            if hook_path is None:
                out.warnings.append(
                    f"plugin {plugin.name}: hooks path escapes plugin dir: {item}"
                )
                continue
            try:
                raw: Any = json.loads(hook_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                out.warnings.append(
                    f"plugin {plugin.name}: failed to load hooks file {item}: {exc}"
                )
                continue
        elif isinstance(item, dict):
            raw = item
        else:
            continue

        # Unwrap an optional ``{"hooks": ...}`` envelope.
        inner = raw.get("hooks", raw) if isinstance(raw, dict) else raw
        if isinstance(inner, dict) and "event" in inner:
            # Native single inline entry.
            _append_native_hook(plugin, inner, out)
        elif isinstance(inner, dict):
            # Claude Code / CodeBuddy event-keyed schema.
            _append_foreign_hooks(plugin, inner, out)
        elif isinstance(inner, list):
            # Native flat list of entries.
            for raw_entry in inner:
                if isinstance(raw_entry, dict):
                    _append_native_hook(plugin, raw_entry, out)


def _collect_mcp(plugin: LoadedPlugin, out: PluginContributions) -> None:
    spec = plugin.manifest.mcp_servers
    if spec is None:
        return
    servers: list[McpServerConfig] = []
    if isinstance(spec, str):
        mcp_path = (plugin.path / spec).resolve()
        try:
            mcp_path.relative_to(plugin.path.resolve())
            servers = load_mcp_config(mcp_path)
        except (OSError, ValueError) as exc:
            out.warnings.append(
                f"plugin {plugin.name}: failed to load MCP config {spec}: {exc}"
            )
            return
    elif isinstance(spec, dict):
        doc = spec if ("servers" in spec or "mcpServers" in spec) else {"servers": spec}
        try:
            servers = servers_from_document(doc)
        except ValueError as exc:
            out.warnings.append(f"plugin {plugin.name}: invalid MCP config: {exc}")
            return

    declared_caps = capability_values_from_permissions(plugin.manifest.permissions)
    for server in servers:
        name = (
            server.name
            if server.name == plugin.name
            else f"{plugin.name}-{server.name}"
        )
        server.name = name
        if server.command:
            server.command = _substitute(server.command, plugin.path)
        server.args = [_substitute(a, plugin.path) for a in server.args]
        server.env = {k: _substitute(v, plugin.path) for k, v in server.env.items()}
        # Defer loading by default: plugin servers don't spawn at app
        # launch (start_all skips lazy servers); they connect on first
        # tool call / discovery. A manifest can opt out with lazy=false.
        if server.lazy is None:
            server.lazy = True
        if declared_caps and not server.capabilities:
            server.capabilities = list(declared_caps)
        out.mcp_servers.append(server)


def merge_plugin_skills(
    registry: SkillRegistry, contributions: PluginContributions
) -> None:
    """Merge plugin skills into a workspace registry (workspace wins)."""
    seen = {s.name.lower() for s in registry.skills}
    for skill in contributions.skills:
        if skill.name.lower() not in seen:
            registry.skills.append(skill)
            seen.add(skill.name.lower())
    registry.warnings.extend(contributions.warnings)


# ── Install / lifecycle ──────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_manifest_root(staging: Path) -> Path | None:
    """Manifest at staging root, or exactly one level down."""
    if load_plugin_manifest(staging) is not None:
        return staging
    for child in sorted(staging.iterdir()):
        if child.is_dir() and load_plugin_manifest(child) is not None:
            return child
    return None


def install_plugin(
    spec: str,
    plugins_dir: Path | None = None,
    *,
    trust: bool = False,
    max_size_bytes: int = PLUGIN_MAX_SIZE_BYTES,
) -> tuple[InstallOutcome, str]:
    """Install a plugin from ``github:owner/repo``, a local directory, or
    ``<plugin>@<marketplace>`` (a marketplace registered via
    :func:`add_marketplace`).

    Records the install in the scope lockfile (enabled, untrusted unless
    ``trust``). Returns ``(outcome, message)``.
    """
    target_dir = plugins_dir or user_plugins_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    # <plugin>@<marketplace> — resolve through the registered marketplace.
    # A bare existing dir wins (a local path could match the same shape).
    at_spec = parse_plugin_at_marketplace(spec)
    if at_spec is not None and not Path(spec).is_dir():
        plugin_name, marketplace_name = at_spec
        src = resolve_marketplace_plugin(plugin_name, marketplace_name)
        if src is None:
            return (
                InstallOutcome.FAILED,
                f"Plugin {plugin_name} not found in marketplace "
                f"{marketplace_name} (register it with "
                f"`plugin marketplace add <github:owner/repo|path>`)",
            )
        # Record the ``@`` spec so update re-resolves through the
        # marketplace (picking up refreshed copies).
        return _install_from_local(src, target_dir, spec.strip(), trust=trust)

    source = InstallSource.parse(spec)
    if source.kind == "local":
        src = Path(source.local_path)
        # Store the bare absolute path (not ``local:<path>``): the recorded
        # source must round-trip through ``InstallSource.parse`` for
        # ``update_plugin`` to re-resolve it, and that parser recognizes a
        # bare existing dir, not a ``local:`` prefix. Absolute so a later
        # update from a different cwd still resolves.
        return _install_from_local(src, target_dir, str(src.resolve()), trust=trust)

    if source.kind == "github":
        return _install_from_github(
            source, target_dir, trust=trust, max_size_bytes=max_size_bytes
        )

    return (InstallOutcome.FAILED, f"Invalid plugin source: {spec}")


def _install_from_local(
    src: Path, target_dir: Path, source_spec: str, *, trust: bool
) -> tuple[InstallOutcome, str]:
    """Copy a local plugin dir into the scope dir and record the install."""
    manifest = load_plugin_manifest(src)
    if manifest is None:
        return (InstallOutcome.FAILED, f"No plugin manifest found in {src}")
    dest = target_dir / manifest.name
    if dest.exists():
        return (
            InstallOutcome.ALREADY_EXISTS,
            f"Plugin {manifest.name} already exists at {dest}",
        )
    shutil.copytree(src, dest)
    _finalize_installed_plugin(dest)
    _record_install(target_dir, manifest, source_spec, trust)
    return (
        InstallOutcome.INSTALLED,
        _install_message(manifest, dest, trust),
    )


def _install_from_github(
    source: InstallSource,
    target_dir: Path,
    *,
    trust: bool,
    max_size_bytes: int,
) -> tuple[InstallOutcome, str]:
    """Download + extract a plugin repo. Reuses the hardened skill
    download/extract path (size caps, traversal guard, symlink reject)."""
    urls = [
        u
        for u in _github_archive_urls(source)
        if _host_is_allowed(u, GITHUB_ALLOWED_HOSTS)
    ]
    if not urls:
        return (InstallOutcome.FAILED, "No allowed archive URLs for source")

    data: bytes | None = None
    last_error = ""
    for candidate in urls:
        try:
            data = _stream_download(candidate, max_size_bytes)
            break
        except _DownloadTooLarge as exc:
            return (
                InstallOutcome.FAILED,
                f"Download exceeds {max_size_bytes} bytes: {exc}",
            )
        except _DownloadMissing:
            last_error = f"{candidate}: not found"
            continue
        except Exception as exc:  # noqa: BLE001 — surface any failure
            last_error = f"{candidate}: {exc}"
            continue
    if data is None:
        return (InstallOutcome.FAILED, f"Download failed: {last_error or 'unknown'}")

    staging = target_dir / f".{source.repo}.tmp"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    try:
        _extract_tarball(data, staging, max_size_bytes=max_size_bytes)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"Extract failed: {exc}")

    root = _find_manifest_root(staging)
    if root is None:
        shutil.rmtree(staging, ignore_errors=True)
        return (
            InstallOutcome.FAILED,
            "No plugin manifest in repo (looked at top level and one nested dir)",
        )
    manifest = load_plugin_manifest(root)
    assert manifest is not None
    dest = target_dir / manifest.name
    if dest.exists():
        shutil.rmtree(staging, ignore_errors=True)
        return (
            InstallOutcome.ALREADY_EXISTS,
            f"Plugin {manifest.name} already exists at {dest}",
        )
    try:
        root.rename(dest)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"Atomic rename failed: {exc}")
    if root != staging:
        shutil.rmtree(staging, ignore_errors=True)

    _finalize_installed_plugin(dest)
    _record_install(
        target_dir, manifest, f"github:{source.owner}/{source.repo}", trust
    )
    return (InstallOutcome.INSTALLED, _install_message(manifest, dest, trust))


def _record_install(
    plugins_dir: Path, manifest: PluginManifest, source_spec: str, trust: bool
) -> None:
    _update_lockfile_entry(
        plugins_dir,
        manifest.name,
        source=source_spec,
        version=manifest.version,
        installed_at=_now_iso(),
        enabled=True,
        trusted=trust,
    )


def _finalize_installed_plugin(dest: Path) -> None:
    """Normalize the installed copy into canonical form (best-effort).

    Never raises: a normalization failure must not break the install — the
    runtime loader's tolerance shims still load the un-normalized copy.
    """
    try:
        notes = normalize_installed_plugin(dest)
        if notes:
            _LOG.info("normalized plugin %s: %s", dest.name, "; ".join(notes))
    except Exception as exc:  # noqa: BLE001 — normalization is best-effort
        _LOG.warning("plugin normalization skipped for %s: %s", dest, exc)


def _install_message(manifest: PluginManifest, dest: Path, trust: bool) -> str:
    parts = [f"Installed plugin {manifest.name} v{manifest.version} to {dest}"]
    components: list[str] = []
    if manifest.skills:
        components.append("skills")
    if manifest.commands:
        components.append("commands")
    if manifest.agents:
        components.append("agents")
    if manifest.rules:
        components.append("rules")
    if manifest.hooks:
        components.append("hooks")
    if manifest.mcp_servers:
        components.append("MCP servers")
    if components:
        parts.append(f"Components: {', '.join(components)}.")
    if not trust and (manifest.hooks or manifest.mcp_servers):
        parts.append(
            "Hooks/MCP servers stay inactive until you run "
            f"`deepseek-tui plugin trust {manifest.name}`."
        )
    return " ".join(parts)


_SCAFFOLD_SKILL_TEMPLATE = """\
---
name: {name}
description: Describe when this skill should be used — the model reads this line to decide.
---

# {name}

Write the skill's instructions here. Keep the body focused; move long
reference material into a `references/` subdirectory and link to it.
"""


def scaffold_plugin(name: str, parent_dir: Path) -> tuple[InstallOutcome, str]:
    """Generate a canonical (Claude-layout) plugin skeleton at
    ``<parent_dir>/<name>``: ``.claude-plugin/plugin.json`` + one example
    skill. Fails when the directory already exists.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        return (
            InstallOutcome.FAILED,
            "Plugin names must be lowercase kebab-case (e.g. my-plugin)",
        )
    dest = parent_dir / name
    if dest.exists():
        return (InstallOutcome.FAILED, f"Directory already exists: {dest}")
    manifest_dir = dest / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps(
            {"name": name, "version": "0.1.0", "description": ""},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    skill_dir = dest / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        _SCAFFOLD_SKILL_TEMPLATE.format(name=name), encoding="utf-8"
    )
    return (
        InstallOutcome.INSTALLED,
        f"Created plugin skeleton at {dest}. Layout: .claude-plugin/plugin.json "
        f"+ skills/{name}/SKILL.md. Add agents/*.md, commands/*.md, "
        "hooks/hooks.json or .mcp.json at the root as needed — they are "
        "auto-discovered. Test with `deepseek-tui plugin doctor "
        f"{dest}`, install with `deepseek-tui plugin install {dest}`.",
    )


def uninstall_plugin(name: str, plugins_dir: Path | None = None) -> str:
    """Remove a plugin directory and its lockfile entry."""
    target_dir = plugins_dir or user_plugins_dir()
    plugin_path = target_dir / name
    if not plugin_path.is_dir():
        return f"Plugin not found: {name}"
    shutil.rmtree(plugin_path)
    plugins = read_lockfile(target_dir)
    if name in plugins:
        del plugins[name]
        _write_lockfile(target_dir, plugins)
    return f"Uninstalled plugin {name}"


def update_plugin(
    name: str, plugins_dir: Path | None = None
) -> tuple[InstallOutcome, str]:
    """Re-install a plugin from its recorded source spec.

    Installs into a staging dir first, then swaps via
    ``live → backup → staged → live`` so a crash mid-swap can still roll
    back to the previous copy. Failed re-installs never delete the live
    plugin. Claude Code interop plugins (files owned by ``~/.claude``, no
    reinstallable source of ours) are refused.
    """
    target_dir = plugins_dir or user_plugins_dir()
    entry = read_lockfile(target_dir).get(name)
    if entry is None:
        return (InstallOutcome.FAILED, f"Plugin not in lockfile: {name}")
    plugin_path = target_dir / name
    if not plugin_path.is_dir() and any(
        manifest.name == name for manifest, _ in discover_claude_plugins()
    ):
        return (
            InstallOutcome.FAILED,
            f"Plugin {name} is managed by Claude Code; update it there",
        )
    spec = str(entry.get("source", ""))
    if not spec:
        return (InstallOutcome.FAILED, f"No source recorded for {name}")
    was_trusted = bool(entry.get("trusted", False))
    was_enabled = bool(entry.get("enabled", True))

    staging = target_dir / f".update-staging-{name}"
    backup = target_dir / f".update-backup-{name}"
    if staging.exists():
        shutil.rmtree(staging)
    if backup.exists():
        shutil.rmtree(backup)
    staging.mkdir(parents=True, exist_ok=True)
    staged_manifest: PluginManifest | None = None
    try:
        outcome, message = install_plugin(spec, staging, trust=was_trusted)
        if outcome != InstallOutcome.INSTALLED:
            return (outcome, message)
        staged_plugin = staging / name
        if not staged_plugin.is_dir():
            return (
                InstallOutcome.FAILED,
                f"Re-installed source for {name} produced a different plugin name",
            )
        staged_manifest = load_plugin_manifest(staged_plugin)

        # live → backup, then staged → live. If the second replace fails,
        # restore backup so the user never loses the previous install.
        if plugin_path.is_dir():
            os.replace(plugin_path, backup)
        try:
            os.replace(staged_plugin, plugin_path)
        except BaseException:
            if backup.is_dir() and not plugin_path.exists():
                try:
                    os.replace(backup, plugin_path)
                except OSError:
                    pass
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        # Orphan backup from a previous crashed update — keep live intact.
        if backup.exists() and plugin_path.is_dir():
            shutil.rmtree(backup, ignore_errors=True)

    # Refresh live lockfile (staging's lockfile was discarded with staging).
    # Preserve enabled/trusted; update source/version/installed_at.
    fields: dict[str, Any] = {
        "source": spec,
        "enabled": was_enabled,
        "trusted": was_trusted,
        "installed_at": _now_iso(),
    }
    if staged_manifest is not None and staged_manifest.version:
        fields["version"] = staged_manifest.version
    _update_lockfile_entry(target_dir, name, **fields)
    return (InstallOutcome.UPDATED, f"Updated {name} from {spec}")


def _plugin_known(name: str, target_dir: Path) -> bool:
    """Plugin exists in the scope dir, or (user scope) via Claude Code."""
    if (target_dir / name).is_dir():
        return True
    try:
        is_user_scope = target_dir.resolve() == user_plugins_dir().resolve()
    except OSError:
        return False
    if not is_user_scope:
        return False
    return any(
        manifest.name == name for manifest, _ in discover_claude_plugins()
    )


def set_plugin_enabled(
    name: str, enabled: bool, plugins_dir: Path | None = None
) -> str:
    target_dir = plugins_dir or user_plugins_dir()
    if not _plugin_known(name, target_dir):
        return f"Plugin not found: {name}"
    target_dir.mkdir(parents=True, exist_ok=True)
    _update_lockfile_entry(target_dir, name, enabled=enabled)
    return f"{'Enabled' if enabled else 'Disabled'} plugin {name}"


def set_plugin_trusted(
    name: str, trusted: bool, plugins_dir: Path | None = None
) -> str:
    target_dir = plugins_dir or user_plugins_dir()
    if not _plugin_known(name, target_dir):
        return f"Plugin not found: {name}"
    target_dir.mkdir(parents=True, exist_ok=True)
    _update_lockfile_entry(target_dir, name, trusted=trusted)
    return f"{'Trusted' if trusted else 'Untrusted'} plugin {name}"


# ── Marketplace registry ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PluginRegistryEntry:
    """One row in the curated plugin registry index.json."""

    name: str
    source: str
    description: str = ""
    version: str = ""
    components: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginRegistryDocument:
    """Deserialized plugins-registry index.json."""

    plugins: tuple[PluginRegistryEntry, ...]

    @classmethod
    def from_json(cls, data: str) -> PluginRegistryDocument:
        raw = json.loads(data)
        entries: list[PluginRegistryEntry] = []
        table = raw.get("plugins", {}) if isinstance(raw, dict) else {}
        if isinstance(table, dict):
            for name, entry in table.items():
                if not isinstance(name, str) or not isinstance(entry, dict):
                    continue
                source = entry.get("source", "")
                if not isinstance(source, str) or not source:
                    continue
                entries.append(
                    PluginRegistryEntry(
                        name=name,
                        source=source,
                        description=str(entry.get("description") or ""),
                        version=str(entry.get("version") or ""),
                        components=_as_str_tuple(entry.get("components")),
                        permissions=_as_str_tuple(entry.get("permissions")),
                    )
                )
        return cls(plugins=tuple(entries))


def fetch_plugin_registry(url: str | None = None) -> PluginRegistryDocument | None:
    """Fetch the remote plugin registry index.

    Same host allow-list and failure semantics as the skill registry:
    returns ``None`` on network/parse failure or a disallowed host.
    """
    import httpx

    target = url or DEFAULT_PLUGIN_REGISTRY_URL
    if not _host_is_allowed(target, REGISTRY_ALLOWED_HOSTS):
        _LOG.warning("plugin registry host not allow-listed: %s", target)
        return None
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(target)
            resp.raise_for_status()
            return PluginRegistryDocument.from_json(resp.text)
    except Exception:  # noqa: BLE001 — registry fetch is best-effort
        _LOG.debug("Failed to fetch plugin registry from %s", target)
        return None


# ── Local marketplace (.claude-plugin/marketplace.json) ──────────────────


@dataclass(frozen=True, slots=True)
class MarketplaceEntry:
    """One local plugin advertised by a repo ``marketplace.json``."""

    name: str
    path: Path  # resolved absolute path to the plugin directory
    description: str = ""
    version: str = ""
    category: str = ""


def load_marketplace(repo: Path) -> list[MarketplaceEntry]:
    """Parse a Claude Code ``marketplace.json`` and resolve local plugins.

    ``repo`` may be the repo root (holding ``.claude-plugin/marketplace.json``)
    or the path to a ``marketplace.json`` directly. Only entries with a local
    ``source`` (a relative/absolute directory path, the mainstream case) are
    returned — remote ``git-subdir`` entries are skipped since they need a
    separate clone step. Raises ``FileNotFoundError`` when no marketplace file
    is present so callers can fall back to single-plugin install.
    """
    repo = repo.expanduser()
    if repo.is_file():
        market_path = repo
    else:
        market_path = repo / ".claude-plugin" / "marketplace.json"
        if not market_path.is_file():
            alt = repo / "marketplace.json"
            market_path = alt if alt.is_file() else market_path
    if not market_path.is_file():
        raise FileNotFoundError(f"No marketplace.json under {repo}")

    base = market_path.parent.parent  # repo root (parent of .claude-plugin)
    raw = json.loads(market_path.read_text(encoding="utf-8"))
    entries: list[MarketplaceEntry] = []
    plugins = raw.get("plugins", []) if isinstance(raw, dict) else []
    if not isinstance(plugins, list):
        return entries
    for item in plugins:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        source = item.get("source")
        if not isinstance(name, str) or not name:
            continue
        # Local sources are plain path strings; remote sources are dicts.
        if not isinstance(source, str):
            continue
        src_path = Path(source)
        if not src_path.is_absolute():
            src_path = (base / src_path).resolve()
        if not src_path.is_dir():
            continue
        entries.append(
            MarketplaceEntry(
                name=name,
                path=src_path,
                description=str(item.get("description") or ""),
                version=str(item.get("version") or ""),
                category=str(item.get("category") or ""),
            )
        )
    return entries


# ── Registered marketplaces (two-level install model) ───────────────────
#
# Claude Code's distribution model: register a marketplace repo once
# (``plugin marketplace add owner/repo``), then install individual plugins
# from it (``plugin install <plugin>@<marketplace>``). GitHub marketplaces
# are downloaded to ``~/.deepseek/marketplaces/<name>/``; local ones are
# referenced in place (the user's checkout stays authoritative). The
# registry file records name → source/path.

MARKETPLACES_REGISTRY_NAME = "marketplaces.json"

# A marketplace repo bundles many plugins (agents-main ships 88); allow a
# far larger archive than a single plugin while keeping a bomb guard.
MARKETPLACE_MAX_SIZE_BYTES = 100 * 1024 * 1024

_PLUGIN_AT_MARKETPLACE_RE = re.compile(
    r"^(?P<plugin>[A-Za-z0-9][A-Za-z0-9._-]*)@(?P<marketplace>[A-Za-z0-9][A-Za-z0-9._-]*)$"
)


def marketplaces_dir() -> Path:
    """``~/.deepseek/marketplaces/`` — registered marketplace repos."""
    from deepseek_tui.config.paths import user_deepseek_dir

    return user_deepseek_dir() / "marketplaces"


def parse_plugin_at_marketplace(spec: str) -> tuple[str, str] | None:
    """Parse ``<plugin>@<marketplace>``, or ``None`` when not that shape."""
    match = _PLUGIN_AT_MARKETPLACE_RE.match(spec.strip())
    if match is None:
        return None
    return (match.group("plugin"), match.group("marketplace"))


def read_marketplaces(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Read the marketplace registry. Missing/corrupt → empty mapping."""
    base = root or marketplaces_dir()
    path = base / MARKETPLACES_REGISTRY_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("failed to read marketplace registry %s: %s", path, exc)
        return {}
    table = data.get("marketplaces") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return {}
    return {k: v for k, v in table.items() if isinstance(v, dict)}


def _write_marketplaces(base: Path, table: dict[str, dict[str, Any]]) -> None:
    from deepseek_tui.utils import write_json_atomic

    write_json_atomic(
        base / MARKETPLACES_REGISTRY_NAME, {"version": 1, "marketplaces": table}
    )


def _marketplace_json_path(repo: Path) -> Path | None:
    for candidate in (repo / ".claude-plugin" / "marketplace.json", repo / "marketplace.json"):
        if candidate.is_file():
            return candidate
    return None


def _marketplace_display_name(repo: Path, fallback: str) -> str:
    """The ``name`` field of marketplace.json, or ``fallback``."""
    path = _marketplace_json_path(repo)
    if path is None:
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    name = data.get("name") if isinstance(data, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return fallback


def _find_marketplace_root(staging: Path) -> Path | None:
    """marketplace.json at staging root, or exactly one level down."""
    if _marketplace_json_path(staging) is not None:
        return staging
    for child in sorted(staging.iterdir()):
        if child.is_dir() and _marketplace_json_path(child) is not None:
            return child
    return None


def add_marketplace(
    spec: str,
    root: Path | None = None,
    *,
    max_size_bytes: int = MARKETPLACE_MAX_SIZE_BYTES,
) -> tuple[InstallOutcome, str]:
    """Register a marketplace from ``github:owner/repo`` or a local path.

    GitHub sources are downloaded (hardened tarball path) into the
    marketplaces dir; local sources are referenced in place. Returns
    ``(outcome, message)``.
    """
    base = root or marketplaces_dir()
    base.mkdir(parents=True, exist_ok=True)

    source = InstallSource.parse(spec)
    if source.kind == "local":
        repo = Path(source.local_path).expanduser().resolve()
        try:
            entries = load_marketplace(repo)
        except FileNotFoundError:
            return (InstallOutcome.FAILED, f"No marketplace.json under {repo}")
        name = _marketplace_display_name(repo, repo.name)
        table = read_marketplaces(base)
        if name in table:
            return (
                InstallOutcome.ALREADY_EXISTS,
                f"Marketplace {name} already registered",
            )
        table[name] = {
            "source": str(repo),
            "path": str(repo),
            "added_at": _now_iso(),
        }
        _write_marketplaces(base, table)
        return (
            InstallOutcome.INSTALLED,
            f"Registered marketplace {name} ({len(entries)} plugins) from {repo}. "
            f"Install one with `plugin install <name>@{name}`.",
        )

    if source.kind == "github":
        return _add_marketplace_from_github(
            source, base, spec, max_size_bytes=max_size_bytes
        )

    return (InstallOutcome.FAILED, f"Invalid marketplace source: {spec}")


def _add_marketplace_from_github(
    source: InstallSource,
    base: Path,
    spec: str,
    *,
    max_size_bytes: int,
) -> tuple[InstallOutcome, str]:
    urls = [
        u
        for u in _github_archive_urls(source)
        if _host_is_allowed(u, GITHUB_ALLOWED_HOSTS)
    ]
    if not urls:
        return (InstallOutcome.FAILED, "No allowed archive URLs for source")

    data: bytes | None = None
    last_error = ""
    for candidate in urls:
        try:
            data = _stream_download(candidate, max_size_bytes)
            break
        except _DownloadTooLarge as exc:
            return (
                InstallOutcome.FAILED,
                f"Download exceeds {max_size_bytes} bytes: {exc}",
            )
        except _DownloadMissing:
            last_error = f"{candidate}: not found"
            continue
        except Exception as exc:  # noqa: BLE001 — surface any failure
            last_error = f"{candidate}: {exc}"
            continue
    if data is None:
        return (InstallOutcome.FAILED, f"Download failed: {last_error or 'unknown'}")

    staging = base / f".{source.repo}.tmp"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    try:
        _extract_tarball(data, staging, max_size_bytes=max_size_bytes)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"Extract failed: {exc}")

    repo_root = _find_marketplace_root(staging)
    if repo_root is None:
        shutil.rmtree(staging, ignore_errors=True)
        return (
            InstallOutcome.FAILED,
            "No marketplace.json in repo (looked at top level and one nested dir)",
        )
    name = _marketplace_display_name(repo_root, source.repo)
    table = read_marketplaces(base)
    dest = base / name
    if name in table or dest.exists():
        shutil.rmtree(staging, ignore_errors=True)
        return (
            InstallOutcome.ALREADY_EXISTS,
            f"Marketplace {name} already registered",
        )
    try:
        repo_root.rename(dest)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"Atomic rename failed: {exc}")
    if repo_root != staging:
        shutil.rmtree(staging, ignore_errors=True)

    try:
        count = len(load_marketplace(dest))
    except FileNotFoundError:
        count = 0
    table[name] = {"source": spec, "path": str(dest), "added_at": _now_iso()}
    _write_marketplaces(base, table)
    return (
        InstallOutcome.INSTALLED,
        f"Registered marketplace {name} ({count} plugins) from {spec}. "
        f"Install one with `plugin install <name>@{name}`.",
    )


def remove_marketplace(name: str, root: Path | None = None) -> str:
    """Unregister a marketplace; delete its downloaded copy (never a local
    checkout referenced in place)."""
    base = root or marketplaces_dir()
    table = read_marketplaces(base)
    entry = table.pop(name, None)
    if entry is None:
        return f"Marketplace not found: {name}"
    path_str = entry.get("path")
    if isinstance(path_str, str):
        path = Path(path_str)
        try:
            inside = path.resolve().is_relative_to(base.resolve())
        except OSError:
            inside = False
        if inside and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    _write_marketplaces(base, table)
    return f"Removed marketplace {name}"


def update_marketplace(
    name: str,
    root: Path | None = None,
    *,
    max_size_bytes: int = MARKETPLACE_MAX_SIZE_BYTES,
) -> tuple[InstallOutcome, str]:
    """Refresh a GitHub marketplace's downloaded copy from its source.

    Local marketplaces track their directory in place, so there is nothing
    to refresh. The swap is staged: a failed re-download never deletes the
    existing copy.
    """
    base = root or marketplaces_dir()
    table = read_marketplaces(base)
    entry = table.get(name)
    if entry is None:
        return (InstallOutcome.FAILED, f"Marketplace not found: {name}")
    spec = str(entry.get("source", ""))
    if not spec.startswith("github:"):
        return (
            InstallOutcome.UPDATED,
            f"Marketplace {name} tracks a local directory; nothing to update",
        )

    staging_root = base / f".update-{name}"
    if staging_root.exists():
        shutil.rmtree(staging_root, ignore_errors=True)
    staging_root.mkdir(parents=True)
    try:
        outcome, message = _add_marketplace_from_github(
            InstallSource.parse(spec), staging_root, spec,
            max_size_bytes=max_size_bytes,
        )
        if outcome != InstallOutcome.INSTALLED:
            return (outcome, message)
        staged = staging_root / name
        if not staged.is_dir():
            return (
                InstallOutcome.FAILED,
                f"Re-downloaded source for {name} produced a different name",
            )
        live = base / name
        backup = base / f".backup-{name}"
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if live.is_dir():
            os.replace(live, backup)
        try:
            os.replace(staged, live)
        except BaseException:
            if backup.is_dir() and not live.exists():
                try:
                    os.replace(backup, live)
                except OSError:
                    pass
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)

    table[name] = {"source": spec, "path": str(base / name), "added_at": _now_iso()}
    _write_marketplaces(base, table)
    return (InstallOutcome.UPDATED, f"Updated marketplace {name} from {spec}")


def resolve_marketplace_plugin(
    plugin_name: str, marketplace_name: str, root: Path | None = None
) -> Path | None:
    """Resolve ``<plugin>@<marketplace>`` to the plugin's local directory."""
    base = root or marketplaces_dir()
    entry = read_marketplaces(base).get(marketplace_name)
    if entry is None:
        return None
    repo = Path(str(entry.get("path", "")))
    if not repo.is_dir():
        return None
    try:
        entries = load_marketplace(repo)
    except FileNotFoundError:
        return None
    for item in entries:
        if item.name.lower() == plugin_name.lower():
            return item.path
    return None
