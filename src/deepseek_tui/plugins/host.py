"""Deep plugin-host module with a small lifecycle interface.

This is the migration seam between callers and the existing plugin
implementation.  Source/format adapters and immutable storage can replace the
legacy backend later without changing Engine, CLI, or REST callers again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeAlias

from deepseek_tui.plugins.model import (
    CompatibilityStatus,
    DerivedPlugin,
    Diagnostic,
)


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


PluginOperation: TypeAlias = (
    InstallPlugin | UpdatePlugin | RemovePlugin | EnablePlugin | TrustPlugin
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

    def plugin(self, name: str) -> Any | None:
        return self._by_name.get(name.lower())

    def activate(self, name: str) -> PluginActivation | None:
        """Load declarative bodies for one package captured by this session."""
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

        if isinstance(operation, InstallPlugin):
            local_source = Path(operation.source).expanduser()
            if local_source.is_dir():
                return self._install_local_candidate(operation, local_source)
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
            return PluginOperationResult("removed", message)
        if isinstance(operation, EnablePlugin):
            message = set_plugin_enabled(
                operation.name,
                operation.enabled,
                operation.plugins_dir,
            )
            return PluginOperationResult("applied", message)
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
        if explicit_ref:
            return PluginOperationResult(
                "failed",
                "Remote git-subdir entries with an explicit ref are not supported yet",
            )
        try:
            remote = GitSubdirSource.parse(
                package.source.locator,
                package.source.relative_root,
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
            },
        )
        return PluginOperationResult(outcome.value, message)

    def open_session(self, *, workspace: Path) -> PluginSession:
        from deepseek_tui.integrations.plugins import (
            collect_light_contributions,
            collect_skill_contributions,
            discover_plugins,
        )

        plugins = discover_plugins(workspace=workspace)
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
