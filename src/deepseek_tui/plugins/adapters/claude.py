from __future__ import annotations

from pathlib import Path
from typing import Any

from deepseek_tui.plugins.adapters.common import (
    declared_paths,
    markdown_files,
    markdown_metadata,
    read_json,
    resource_ref,
    scalar_description,
)
from deepseek_tui.plugins.model import (
    ActivationMode,
    CompatibilityReport,
    CompatibilityStatus,
    ContributionSpec,
    DerivedPlugin,
    Diagnostic,
    DiagnosticSeverity,
    PermissionClaim,
    RiskClass,
    SourceProvenance,
)
from deepseek_tui.plugins.source import LocalArtifact, PackageCandidate


class ClaudePluginAdapter:
    adapter_id = "claude"
    adapter_version = 1

    def probe(self, candidate: PackageCandidate) -> int:
        if (candidate.root / ".claude-plugin" / "plugin.json").is_file():
            return 100
        if (candidate.root / ".deepseek-plugin" / "plugin.json").is_file():
            return 85
        if any(
            (candidate.root / path).exists()
            for path in ("skills", "commands", "agents", "hooks/hooks.json", ".mcp.json")
        ):
            return 70
        return 0

    def _manifest(self, root: Path) -> tuple[dict[str, Any], CompatibilityStatus]:
        claude = root / ".claude-plugin" / "plugin.json"
        native = root / ".deepseek-plugin" / "plugin.json"
        if claude.is_file():
            return read_json(claude), CompatibilityStatus.NATIVE
        if native.is_file():
            return read_json(native), CompatibilityStatus.ADAPTED
        return {}, CompatibilityStatus.NATIVE

    def derive(self, artifact: LocalArtifact, candidate: PackageCandidate) -> DerivedPlugin:
        manifest, base_status = self._manifest(candidate.root)
        plugin_id = str(manifest.get("name") or candidate.declared_name or candidate.root.name)
        diagnostics: list[Diagnostic] = []
        contributions: list[ContributionSpec] = []

        skills = sorted((candidate.root / "skills").glob("*/SKILL.md"))
        skills.extend(
            markdown_files(
                declared_paths(artifact, candidate, manifest.get("skills", [])),
                skill=True,
            )
        )
        self._append_markdown(
            contributions, candidate, sorted(set(skills)), "prompt.skill", base_status
        )

        for key, folder, kind in (
            ("commands", "commands", "prompt.command"),
            ("agents", "agents", "agent.persona"),
        ):
            paths = (
                declared_paths(artifact, candidate, manifest[key])
                if key in manifest
                else [candidate.root / folder]
            )
            self._append_markdown(
                contributions,
                candidate,
                markdown_files(paths),
                kind,
                base_status,
            )

        hooks_value = manifest.get("hooks")
        hook_paths = declared_paths(artifact, candidate, hooks_value)
        default_hooks = candidate.root / "hooks" / "hooks.json"
        if not hook_paths and default_hooks.is_file():
            hook_paths = [default_hooks]
        for path in hook_paths:
            contributions.append(
                ContributionSpec(
                    "lifecycle.hook",
                    path.stem,
                    "Lifecycle hooks",
                    base_status,
                    ActivationMode.SESSION,
                    RiskClass.PROCESS,
                    (resource_ref(candidate, path),),
                    (PermissionClaim("process.spawn", "hook command execution"),),
                )
            )
        if hooks_value and not hook_paths:
            contributions.append(
                ContributionSpec(
                    "lifecycle.hook",
                    "hooks",
                    "Inline lifecycle hooks",
                    base_status,
                    ActivationMode.SESSION,
                    RiskClass.PROCESS,
                    permissions=(PermissionClaim("process.spawn", "hook command execution"),),
                    metadata={"inline": True},
                )
            )

        mcp_value = manifest.get("mcpServers") or manifest.get("mcp_servers")
        mcp_path = candidate.root / ".mcp.json"
        if mcp_value or mcp_path.is_file():
            resources = (resource_ref(candidate, mcp_path),) if mcp_path.is_file() else ()
            contributions.append(
                ContributionSpec(
                    "runtime.mcp-server",
                    "mcp",
                    "MCP servers",
                    base_status,
                    ActivationMode.ON_DEMAND,
                    RiskClass.PROCESS,
                    resources,
                    (PermissionClaim("process.spawn", "MCP server runtime"),),
                )
            )

        unsupported = [
            key for key in ("outputStyles", "lspServers", "themes", "monitors") if key in manifest
        ]
        for key in unsupported:
            diagnostics.append(
                Diagnostic(
                    "CLAUDE_COMPONENT_UNSUPPORTED",
                    DiagnosticSeverity.WARNING,
                    f"Claude component is not supported yet: {key}",
                    source_path=key,
                )
            )
        status = CompatibilityStatus.DEGRADED if unsupported else base_status
        claims = tuple(
            PermissionClaim(str(item), "plugin manifest declaration")
            for item in manifest.get("permissions", [])
            if isinstance(item, str)
        )
        return DerivedPlugin(
            1,
            plugin_id,
            str(manifest.get("version") or "0.0.0"),
            scalar_description(manifest.get("description")),
            SourceProvenance(
                "local",
                str(artifact.root),
                artifact.digest,
                candidate.relative_root,
            ),
            tuple(contributions),
            claims,
            CompatibilityReport(
                status,
                self.adapter_id,
                self.adapter_version,
                tuple(diagnostics),
            ),
            metadata={"marketplace": candidate.marketplace_entry},
        )

    @staticmethod
    def _append_markdown(
        out: list[ContributionSpec],
        candidate: PackageCandidate,
        files: list[Path],
        kind: str,
        status: CompatibilityStatus,
    ) -> None:
        for path in files:
            metadata, _ = markdown_metadata(path)
            name = str(metadata.get("name") or path.stem)
            out.append(
                ContributionSpec(
                    kind,
                    name,
                    scalar_description(metadata.get("description")),
                    status,
                    ActivationMode.ON_DEMAND,
                    RiskClass.CONTENT,
                    (resource_ref(candidate, path),),
                    metadata={
                        key: value
                        for key, value in metadata.items()
                        if key not in {"name", "description"}
                    },
                )
            )
