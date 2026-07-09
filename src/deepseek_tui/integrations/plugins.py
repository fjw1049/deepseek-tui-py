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
community plugins can be dropped in. Component types we do not support
yet (``commands``, ``agents``, ``outputStyles``, ``lspServers``) are
surfaced as warnings, not errors.

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
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import LifecycleHookEntry
from deepseek_tui.integrations.hooks import LIFECYCLE_EVENTS
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
    _stream_download,
)
from deepseek_tui.mcp.config import McpServerConfig, load_mcp_config, servers_from_document

__all__ = [
    "DEFAULT_PLUGIN_REGISTRY_URL",
    "LOCKFILE_NAME",
    "PLUGIN_MANIFEST_CANDIDATES",
    "LoadedPlugin",
    "PluginContributions",
    "PluginManifest",
    "PluginRegistryDocument",
    "PluginRegistryEntry",
    "capability_values_from_permissions",
    "claude_plugins_dir",
    "collect_contributions",
    "discover_claude_plugins",
    "discover_plugins",
    "fetch_plugin_registry",
    "install_plugin",
    "load_plugin_manifest",
    "merge_plugin_skills",
    "plugins_directories",
    "project_plugins_dir",
    "read_lockfile",
    "set_plugin_enabled",
    "set_plugin_trusted",
    "uninstall_plugin",
    "update_plugin",
    "user_plugins_dir",
]

_LOG = logging.getLogger(__name__)

LOCKFILE_NAME = "installed_plugins.json"

PLUGIN_MANIFEST_CANDIDATES = (
    Path(".deepseek-plugin") / "plugin.json",
    Path(".claude-plugin") / "plugin.json",
    Path("plugin.json"),
)

# Component manifest keys we accept but do not wire yet.
_UNSUPPORTED_COMPONENT_KEYS = ("commands", "agents", "outputStyles", "lspServers")

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


def load_plugin_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Load and parse the plugin manifest, or ``None`` when absent/invalid."""
    manifest_path: Path | None = None
    for candidate in PLUGIN_MANIFEST_CANDIDATES:
        p = plugin_dir / candidate
        if p.is_file():
            manifest_path = p
            break
    if manifest_path is None:
        return None
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
        hooks = ()

    unsupported = tuple(k for k in _UNSUPPORTED_COMPONENT_KEYS if data.get(k))

    return PluginManifest(
        name=name.strip(),
        version=str(data.get("version") or "0.0.0"),
        description=str(data.get("description") or ""),
        skills=_as_str_tuple(data.get("skills")),
        hooks=hooks,
        mcp_servers=data.get("mcpServers", data.get("mcp_servers")),
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


@dataclass(slots=True)
class PluginContributions:
    """Aggregated components from all enabled plugins."""

    skills: list[Skill] = field(default_factory=list)
    hook_entries: list[LifecycleHookEntry] = field(default_factory=list)
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _substitute(value: str, plugin_dir: Path) -> str:
    return value.replace(_PLUGIN_DIR_TOKEN, str(plugin_dir))


def collect_contributions(plugins: list[LoadedPlugin]) -> PluginContributions:
    """Fan a plugin list out into per-subsystem contribution lists.

    Skills always load. Hooks / MCP servers require ``trusted``.
    """
    out = PluginContributions()
    for plugin in plugins:
        _collect_skills(plugin, out)
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
    for rel in plugin.manifest.skills:
        skills_dir = (plugin.path / rel).resolve()
        try:
            skills_dir.relative_to(plugin.path.resolve())
        except ValueError:
            out.warnings.append(
                f"plugin {plugin.name}: skills path escapes plugin dir: {rel}"
            )
            continue
        reg = SkillRegistry.discover(skills_dir)
        out.skills.extend(reg.skills)
        out.warnings.extend(reg.warnings)


def _collect_hooks(plugin: LoadedPlugin, out: PluginContributions) -> None:
    for item in plugin.manifest.hooks:
        entries: list[dict[str, Any]] = []
        if isinstance(item, str):
            hook_path = (plugin.path / item).resolve()
            try:
                hook_path.relative_to(plugin.path.resolve())
                raw = json.loads(hook_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                out.warnings.append(
                    f"plugin {plugin.name}: failed to load hooks file {item}: {exc}"
                )
                continue
            if isinstance(raw, dict):
                raw = raw.get("hooks", [])
            if isinstance(raw, list):
                entries = [e for e in raw if isinstance(e, dict)]
        elif isinstance(item, dict):
            entries = [item]

        for raw_entry in entries:
            event = raw_entry.get("event")
            command = raw_entry.get("command")
            if event not in LIFECYCLE_EVENTS or not isinstance(command, str):
                out.warnings.append(
                    f"plugin {plugin.name}: invalid hook entry skipped "
                    f"(event={event!r})"
                )
                continue
            out.hook_entries.append(
                LifecycleHookEntry(
                    event=event,
                    command=_substitute(command, plugin.path),
                    condition=raw_entry.get("condition"),
                    timeout_secs=float(raw_entry.get("timeout_secs", 30.0)),
                    background=bool(raw_entry.get("background", False)),
                    continue_on_error=bool(raw_entry.get("continue_on_error", True)),
                    name=f"{plugin.name}:{raw_entry.get('name') or event}",
                )
            )


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
    """Install a plugin from ``github:owner/repo`` or a local directory.

    Records the install in the scope lockfile (enabled, untrusted unless
    ``trust``). Returns ``(outcome, message)``.
    """
    target_dir = plugins_dir or user_plugins_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    source = InstallSource.parse(spec)
    if source.kind == "local":
        src = Path(source.local_path)
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
        # Store the bare absolute path (not ``local:<path>``): the recorded
        # source must round-trip through ``InstallSource.parse`` for
        # ``update_plugin`` to re-resolve it, and that parser recognizes a
        # bare existing dir, not a ``local:`` prefix. Absolute so a later
        # update from a different cwd still resolves.
        _record_install(target_dir, manifest, str(src.resolve()), trust)
        return (
            InstallOutcome.INSTALLED,
            _install_message(manifest, dest, trust),
        )

    if source.kind == "github":
        return _install_from_github(
            source, target_dir, trust=trust, max_size_bytes=max_size_bytes
        )

    return (InstallOutcome.FAILED, f"Invalid plugin source: {spec}")


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


def _install_message(manifest: PluginManifest, dest: Path, trust: bool) -> str:
    parts = [f"Installed plugin {manifest.name} v{manifest.version} to {dest}"]
    components: list[str] = []
    if manifest.skills:
        components.append("skills")
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
