"""Deep plugin-host module with a small lifecycle interface.

This is the migration seam between callers and the existing plugin
implementation.  Source/format adapters and immutable storage can replace the
legacy backend later without changing Engine, CLI, or REST callers again.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeAlias

from deepseek_tui.plugins.model import (
    CompatibilityStatus,
    DerivedPlugin,
    Diagnostic,
)
from deepseek_tui.plugins.runtime_ports import LeaseBag


@dataclass(frozen=True, slots=True)
class PluginSummary:
    name: str
    version: str
    description: str
    scope: str
    enabled: bool
    trusted: bool
    path: Path
    contribution_index: dict[str, Any] | None
    permissions: tuple[str, ...]
    components: dict[str, bool]


@dataclass(frozen=True, slots=True)
class PluginInspection:
    plugins: tuple[PluginSummary, ...]
    candidates: tuple[DerivedPlugin, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class InstallPlugin:
    source: str
    plugins_dir: Path | None = None
    trust: bool = False
    plugin_id: str | None = None
    candidate_root: str | None = None


@dataclass(frozen=True, slots=True)
class UpdatePlugin:
    name: str
    plugins_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class RemovePlugin:
    name: str
    plugins_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class EnablePlugin:
    name: str
    enabled: bool
    plugins_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class TrustPlugin:
    name: str
    trusted: bool
    plugins_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class GrantPlugin:
    name: str
    digest: str
    plugins_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class RevokePlugin:
    name: str
    digest: str | None = None
    plugins_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class GcPlugins:
    dry_run: bool = False
    plugins_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class RollbackPlugin:
    name: str
    digest: str
    plugins_dir: Path | None = None


PluginOperation: TypeAlias = (
    InstallPlugin
    | UpdatePlugin
    | RemovePlugin
    | EnablePlugin
    | TrustPlugin
    | GrantPlugin
    | RevokePlugin
    | GcPlugins
    | RollbackPlugin
)


@dataclass(frozen=True, slots=True)
class PluginOperationResult:
    outcome: str
    message: str


@dataclass(slots=True)
class PluginStartup:
    hook_entries: list[Any] = field(default_factory=list)
    mcp_servers: list[Any] = field(default_factory=list)
    skills: list[Any] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        """Legacy-compatible name while callers migrate to diagnostics."""
        return self.diagnostics


@dataclass(slots=True)
class PluginActivation:
    commands: list[Any] = field(default_factory=list)
    agents: list[Any] = field(default_factory=list)
    rules: list[Any] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


class PluginSession:
    """Frozen plugin view for one Engine session."""

    def __init__(
        self,
        *,
        workspace: Path,
        loaded_plugins: list[Any],
        startup: PluginStartup,
        snapshot_id: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.loaded_plugins = tuple(loaded_plugins)
        self.startup = startup
        self.catalog = {
            plugin.name: plugin.contribution_index
            for plugin in loaded_plugins
            if plugin.contribution_index
        }
        self._by_name = {plugin.name.lower(): plugin for plugin in loaded_plugins}
        self._activations: dict[str, PluginActivation] = {}
        self._leases = LeaseBag()
        self._closed = False
        self._light_by_name: dict[str, Any] = {}
        self._pi_runtimes: dict[str, Any] = {}
        self.pi_tools: list[Any] = []
        if snapshot_id is None:
            material = "|".join(
                f"{plugin.name}:{plugin.path}:{plugin.enabled}:{plugin.trusted}"
                for plugin in loaded_plugins
            )
            snapshot_id = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
        self.snapshot_id = snapshot_id

    def plugin(self, name: str) -> Any | None:
        return self._by_name.get(name.lower())

    def light_contributions(self, name: str) -> Any | None:
        """Hooks/MCP for one frozen plugin (lazy, session-cached)."""
        if self._closed:
            return None
        key = name.lower()
        cached = self._light_by_name.get(key)
        if cached is not None:
            return cached
        plugin = self._by_name.get(key)
        if plugin is None:
            return None
        from deepseek_tui.integrations.plugins import collect_light_contributions

        contribs = collect_light_contributions([plugin])
        self._light_by_name[key] = contribs
        return contribs

    def invalidate_light(self, name: str) -> None:
        self._light_by_name.pop(name.lower(), None)
        refreshed = self.refresh_plugin_trust(name)
        if refreshed is None:
            return
        self._by_name[name.lower()] = refreshed
        self.loaded_plugins = tuple(
            refreshed if p.name.lower() == name.lower() else p
            for p in self.loaded_plugins
        )

    def refresh_plugin_trust(self, name: str) -> Any | None:
        """Return a LoadedPlugin copy with current lockfile trusted/enabled."""
        plugin = self._by_name.get(name.lower())
        if plugin is None:
            return None
        from deepseek_tui.integrations.plugins import LoadedPlugin, read_lockfile

        try:
            entry = read_lockfile(plugin.path.parent).get(plugin.name, {})
        except Exception:  # noqa: BLE001
            return plugin
        if not isinstance(entry, dict):
            return plugin
        return LoadedPlugin(
            manifest=plugin.manifest,
            path=plugin.path,
            scope=plugin.scope,
            enabled=bool(entry.get("enabled", plugin.enabled)),
            trusted=bool(entry.get("trusted", plugin.trusted)),
            contribution_index=plugin.contribution_index,
        )

    def declared_write_capabilities(self, name: str) -> frozenset[str]:
        plugin = self._by_name.get(name.lower())
        if plugin is None or not getattr(plugin, "trusted", False):
            return frozenset()
        from deepseek_tui.integrations.plugins import (
            capability_values_from_permissions,
        )

        return frozenset(
            capability_values_from_permissions(plugin.manifest.permissions)
        )

    def catalog_entries(self, kind: str | None = None) -> tuple[dict[str, Any], ...]:
        """Thin catalog rows from the frozen contribution indexes."""
        rows: list[dict[str, Any]] = []
        for plugin in self.loaded_plugins:
            index = plugin.contribution_index or {}
            if kind is None:
                rows.append(
                    {
                        "plugin_id": plugin.name,
                        "kinds": {
                            key: index.get(key, [])
                            for key in ("skills", "commands", "agents", "rules")
                        },
                    }
                )
                continue
            key = {
                "prompt.skill": "skills",
                "prompt.command": "commands",
                "agent.persona": "agents",
                "prompt.rule": "rules",
                "skills": "skills",
                "commands": "commands",
                "agents": "agents",
                "rules": "rules",
            }.get(kind, kind)
            for item in index.get(key, []):
                if isinstance(item, dict):
                    rows.append({"plugin_id": plugin.name, **item})
        return tuple(rows)

    def activate(self, name: str) -> PluginActivation | None:
        """Load declarative bodies for one package captured by this session."""
        if self._closed:
            return None
        key = name.lower()
        cached = self._activations.get(key)
        if cached is not None:
            return cached
        plugin = self._by_name.get(key)
        if plugin is None:
            return None

        from deepseek_tui.integrations.plugins import collect_heavy_contributions

        contributions = collect_heavy_contributions([plugin])
        activation = PluginActivation(
            commands=list(contributions.commands),
            agents=list(contributions.agents),
            rules=list(contributions.rules),
            diagnostics=list(contributions.warnings),
        )
        self._activations[key] = activation
        return activation

    async def activate_pi_provider(
        self,
        name: str,
        *,
        tool_registry: Any | None = None,
    ) -> list[Any]:
        """Start the Pi Node sidecar for one trusted plugin and register tools."""
        if self._closed:
            return []
        key = name.lower()
        if key in self._pi_runtimes:
            return [tool for tool in self.pi_tools if tool.name().startswith("pi_")]
        plugin = self._by_name.get(key)
        if plugin is None or not getattr(plugin, "trusted", False):
            return []
        package_json = Path(plugin.path) / "package.json"
        if not package_json.is_file():
            return []
        try:
            import json

            document = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return []
        pi = document.get("pi") if isinstance(document, dict) else None
        if not isinstance(pi, dict) or not pi.get("extensions"):
            return []
        entries = pi.get("extensions")
        if isinstance(entries, str):
            entries = [entries]
        entrypoints = tuple(str(item) for item in entries if isinstance(item, str))
        from deepseek_tui.plugins.pi_runtime import PiNodeRuntime, PiProviderSpec
        from deepseek_tui.plugins.pi_tools import PiBridgeTool
        from deepseek_tui.plugins.runtime_ports import ToolRegistrationLease

        runtime = PiNodeRuntime(
            PiProviderSpec(
                plugin_id=plugin.name,
                package_root=str(Path(plugin.path).resolve()),
                entrypoints=entrypoints,
                cwd=str(self.workspace.resolve()),
            )
        )
        await runtime.start()
        await runtime.session_start()
        self._pi_runtimes[key] = runtime
        tools = []
        for info in await runtime.list_tools():
            tool = PiBridgeTool(
                runtime=runtime,
                info=info,
                owner_plugin_id=plugin.name,
            )
            if tool_registry is not None:
                tool_registry.register_exclusive(tool)
                self._leases.add(ToolRegistrationLease(tool_registry, tool.name()))
            tools.append(tool)
            self.pi_tools.append(tool)
        return tools

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for runtime in list(self._pi_runtimes.values()):
            try:
                await runtime.session_shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                await runtime.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self._pi_runtimes.clear()
        await self._leases.close()


class PluginHost:
    """Public plugin lifecycle interface backed by the legacy implementation."""

    def inspect(
        self,
        *,
        workspace: Path | None = None,
        source: str | Path | None = None,
        include_disabled: bool = True,
    ) -> PluginInspection:
        if source is not None:
            from deepseek_tui.plugins.adapters import inspect_local_source

            candidates, diagnostics = inspect_local_source(source)
            return PluginInspection(
                plugins=(),
                candidates=candidates,
                diagnostics=diagnostics,
            )
        from deepseek_tui.integrations.plugins import discover_plugins

        plugins = discover_plugins(
            workspace=workspace or Path.cwd(),
            include_disabled=include_disabled,
        )
        return PluginInspection(
            plugins=tuple(
                PluginSummary(
                    name=plugin.name,
                    version=plugin.manifest.version,
                    description=plugin.manifest.description,
                    scope=plugin.scope,
                    enabled=plugin.enabled,
                    trusted=plugin.trusted,
                    path=plugin.path,
                    contribution_index=plugin.contribution_index,
                    permissions=tuple(plugin.manifest.permissions),
                    components={
                        "skills": bool(plugin.manifest.skills),
                        "hooks": bool(plugin.manifest.hooks),
                        "mcp_servers": bool(plugin.manifest.mcp_servers),
                        "commands": bool(plugin.manifest.commands),
                        "agents": bool(plugin.manifest.agents),
                        "rules": bool(plugin.manifest.rules),
                    },
                )
                for plugin in plugins
            )
        )

    def apply(self, operation: PluginOperation) -> PluginOperationResult:
        from deepseek_tui.integrations.plugins import (
            install_plugin,
            set_plugin_enabled,
            set_plugin_trusted,
            uninstall_plugin,
            update_plugin,
        )
        from deepseek_tui.plugins.grants import grant_execution, revoke_grant

        if isinstance(operation, InstallPlugin):
            local_source = Path(operation.source).expanduser()
            if local_source.is_dir():
                return self._install_local_candidate(operation, local_source)
            if operation.source.strip().startswith("npm:"):
                outcome, message = install_plugin(
                    operation.source.strip(),
                    operation.plugins_dir,
                    trust=operation.trust,
                )
                return PluginOperationResult(outcome.value, message)
            if operation.plugin_id or operation.candidate_root:
                return PluginOperationResult(
                    "failed",
                    "Plugin candidate selectors currently require a local source directory",
                )
            outcome, message = install_plugin(
                operation.source,
                operation.plugins_dir,
                trust=operation.trust,
            )
            return PluginOperationResult(outcome.value, message)
        if isinstance(operation, UpdatePlugin):
            outcome, message = update_plugin(operation.name, operation.plugins_dir)
            return PluginOperationResult(outcome.value, message)
        if isinstance(operation, RemovePlugin):
            message = uninstall_plugin(operation.name, operation.plugins_dir)
            revoke_grant(operation.name)
            return PluginOperationResult("removed", message)
        if isinstance(operation, EnablePlugin):
            message = set_plugin_enabled(
                operation.name,
                operation.enabled,
                operation.plugins_dir,
            )
            return PluginOperationResult("applied", message)
        if isinstance(operation, GrantPlugin):
            grant_execution(operation.name, operation.digest)
            return PluginOperationResult(
                "granted",
                f"Granted execution for {operation.name}@{operation.digest}",
            )
        if isinstance(operation, RevokePlugin):
            removed = revoke_grant(operation.name, operation.digest)
            return PluginOperationResult(
                "revoked",
                f"Revoked {removed} grant(s) for {operation.name}",
            )
        if isinstance(operation, GcPlugins):
            from deepseek_tui.plugins.store import gc_unreferenced_sources

            removed = gc_unreferenced_sources(dry_run=operation.dry_run)
            verb = "Would remove" if operation.dry_run else "Removed"
            return PluginOperationResult(
                "gc",
                f"{verb} {len(removed)} unreferenced source digest(s)",
            )
        if isinstance(operation, RollbackPlugin):
            from deepseek_tui.integrations.plugins import (
                user_plugins_dir,
            )
            from deepseek_tui.plugins.store import rollback_plugin_link

            target = operation.plugins_dir or user_plugins_dir()
            try:
                path = rollback_plugin_link(target, operation.name, operation.digest)
            except (FileNotFoundError, ValueError, OSError) as exc:
                return PluginOperationResult("failed", str(exc))
            return PluginOperationResult(
                "rolled_back",
                f"Rolled back {operation.name} to {operation.digest} at {path}",
            )
        message = set_plugin_trusted(
            operation.name,
            operation.trusted,
            operation.plugins_dir,
        )
        return PluginOperationResult("applied", message)

    def _install_local_candidate(
        self,
        operation: InstallPlugin,
        source: Path,
    ) -> PluginOperationResult:
        """Select and install one loadable package from a local artifact."""
        from deepseek_tui.integrations.plugins import install_plugin
        from deepseek_tui.plugins.source import PluginSourceError
        from deepseek_tui.plugins.store import write_derived

        try:
            inspection = self.inspect(source=source)
        except PluginSourceError as exc:
            return PluginOperationResult("failed", str(exc))
        candidates = list(inspection.candidates)
        requested_root = _normalize_candidate_root(operation.candidate_root)
        if requested_root is not None:
            candidates = [
                item for item in candidates if item.source.relative_root == requested_root
            ]
        if operation.plugin_id:
            plugin_id = operation.plugin_id.casefold()
            candidates = [
                item for item in candidates if item.plugin_id.casefold() == plugin_id
            ]

        if not candidates:
            selector = operation.candidate_root or operation.plugin_id or "the source"
            return PluginOperationResult(
                "failed",
                f"No plugin candidate matched {selector!r} in {source}",
            )
        if len(candidates) > 1:
            roots = ", ".join(item.source.relative_root for item in candidates)
            if operation.plugin_id:
                return PluginOperationResult(
                    "failed",
                    f"Plugin id {operation.plugin_id!r} is ambiguous; choose "
                    f"candidate_root from: {roots}",
                )
            return PluginOperationResult(
                "failed",
                "Source contains multiple plugin candidates; choose one with "
                f"--plugin. Available: {', '.join(item.plugin_id for item in candidates)}",
            )

        package = candidates[0]
        if package.source.kind == "git-subdir":
            return self._install_remote_candidate(operation, package)
        if (
            package.compatibility.status
            in {CompatibilityStatus.BLOCKED, CompatibilityStatus.UNSUPPORTED}
            or not package.compatibility.can_install
            or not package.compatibility.can_activate
        ):
            return PluginOperationResult(
                "failed",
                f"Plugin {package.plugin_id} was recognized, but activation is blocked "
                f"by adapter {package.compatibility.adapter_id}",
            )
        package_path = _local_package_path(package)
        if package_path is None:
            return PluginOperationResult(
                "failed",
                f"Plugin {package.plugin_id} does not have an installable local source",
            )
        try:
            write_derived(package)
        except (OSError, ValueError):
            pass
        outcome, message = install_plugin(
            str(package_path),
            operation.plugins_dir,
            trust=operation.trust,
            provenance={
                "schema_version": package.schema_version,
                "plugin_id": package.plugin_id,
                "source": package.source.to_dict(),
                "adapter_id": package.compatibility.adapter_id,
                "adapter_version": package.compatibility.adapter_version,
                "compatibility": package.compatibility.to_dict(),
            },
        )
        return PluginOperationResult(outcome.value, message)

    @staticmethod
    def _install_remote_candidate(
        operation: InstallPlugin,
        package: DerivedPlugin,
    ) -> PluginOperationResult:
        from deepseek_tui.integrations.plugins import install_plugin
        from deepseek_tui.plugins.fetch import GitSubdirSource, RemoteFetchError

        source_document = package.metadata.get("marketplace", {}).get("source", {})
        explicit_ref = source_document.get("ref") if isinstance(source_document, dict) else None
        try:
            remote = GitSubdirSource.parse(
                package.source.locator,
                package.source.relative_root
                if not str(package.source.relative_root).startswith("remote:")
                else str(source_document.get("path") or "."),
                ref=str(explicit_ref) if explicit_ref else None,
            )
        except RemoteFetchError as exc:
            return PluginOperationResult("failed", str(exc))
        outcome, message = install_plugin(
            remote.install_spec,
            operation.plugins_dir,
            trust=operation.trust,
            provenance={
                "advertised_plugin_id": package.plugin_id,
                "catalog": package.metadata.get("catalog", {}),
                "source": {
                    "kind": "git-subdir",
                    "locator": package.source.locator,
                    "relative_root": remote.subdir,
                    "ref": remote.ref or "",
                },
            },
        )
        return PluginOperationResult(outcome.value, message)

    def open_session(self, *, workspace: Path) -> PluginSession:
        from deepseek_tui.integrations.plugins import (
            LoadedPlugin,
            build_contribution_index,
            collect_light_contributions,
            collect_skill_contributions,
            discover_plugins,
        )

        plugins = []
        for plugin in discover_plugins(workspace=workspace):
            index = plugin.contribution_index
            if index is None:
                try:
                    # Memory-only catalog for deferred prompt rendering. Never
                    # write the lockfile from open_session / discovery.
                    index = build_contribution_index(plugin.path, plugin.manifest)
                except Exception:  # noqa: BLE001
                    index = None
                plugin = LoadedPlugin(
                    manifest=plugin.manifest,
                    path=plugin.path,
                    scope=plugin.scope,
                    enabled=plugin.enabled,
                    trusted=plugin.trusted,
                    contribution_index=index,
                )
            plugins.append(plugin)
        light = collect_light_contributions(plugins)
        skills = collect_skill_contributions(plugins)
        return PluginSession(
            workspace=workspace,
            loaded_plugins=plugins,
            startup=PluginStartup(
                hook_entries=list(light.hook_entries),
                mcp_servers=list(light.mcp_servers),
                skills=list(skills.skills),
                diagnostics=[*light.warnings, *skills.warnings],
            ),
        )


def merge_session_skills(skill_registry, contribs) -> None:
    """Merge PluginSession skill contributions into a SkillRegistry.

    Thin façade so Engine never imports ``integrations.plugins`` collectors.
    """
    from deepseek_tui.integrations.plugins import merge_plugin_skills

    merge_plugin_skills(skill_registry, contribs)


def _normalize_candidate_root(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized or "."


def _local_package_path(package: DerivedPlugin) -> Path | None:
    if package.source.kind != "local":
        return None
    root = Path(package.source.locator).expanduser().resolve()
    relative = package.source.relative_root
    candidate = root if relative == "." else (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_dir() else None
