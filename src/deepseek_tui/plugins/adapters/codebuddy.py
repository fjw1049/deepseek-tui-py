from __future__ import annotations

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


class CodeBuddyPluginAdapter:
    adapter_id = "codebuddy"
    adapter_version = 1

    def probe(self, candidate: PackageCandidate) -> int:
        return 110 if (candidate.root / ".codebuddy-plugin" / "plugin.json").is_file() else 0

    def derive(self, artifact: LocalArtifact, candidate: PackageCandidate) -> DerivedPlugin:
        manifest = read_json(candidate.root / ".codebuddy-plugin" / "plugin.json")
        contributions: list[ContributionSpec] = []
        diagnostics: list[Diagnostic] = []
        for key, folder, kind, skill in (
            ("skills", "skills", "prompt.skill", True),
            ("commands", "commands", "prompt.command", False),
            ("agents", "agents", "agent.persona", False),
            ("rules", "rules", "prompt.rule", False),
        ):
            paths = (
                declared_paths(artifact, candidate, manifest[key])
                if key in manifest
                else [candidate.root / folder]
            )
            for path in markdown_files(paths, skill=skill):
                metadata, _ = markdown_metadata(path)
                contributions.append(
                    ContributionSpec(
                        kind,
                        str(metadata.get("name") or path.stem),
                        scalar_description(metadata.get("description")),
                        CompatibilityStatus.ADAPTED,
                        (
                            ActivationMode.SESSION
                            if kind == "prompt.rule"
                            else ActivationMode.ON_DEMAND
                        ),
                        RiskClass.CONTENT,
                        (resource_ref(candidate, path),),
                        metadata={
                            field: value
                            for field, value in metadata.items()
                            if field not in {"name", "description"}
                        },
                    )
                )

        hook_paths = declared_paths(artifact, candidate, manifest.get("hooks", []))
        default_hook = candidate.root / "hooks" / "hooks.json"
        if not hook_paths and default_hook.is_file():
            hook_paths = [default_hook]
        for path in hook_paths:
            contributions.append(
                ContributionSpec(
                    "lifecycle.hook",
                    path.stem,
                    "CodeBuddy lifecycle hooks",
                    CompatibilityStatus.ADAPTED,
                    ActivationMode.SESSION,
                    RiskClass.PROCESS,
                    (resource_ref(candidate, path),),
                    (PermissionClaim("process.spawn", "hook command execution"),),
                )
            )

        if manifest.get("expertType") == "team" or manifest.get("teamInfo"):
            diagnostics.append(
                Diagnostic(
                    "CODEBUDDY_TEAM_ORCHESTRATION_DEGRADED",
                    DiagnosticSeverity.WARNING,
                    "agent personas are available but team orchestration is not supported",
                    source_path="teamInfo",
                )
            )
        if manifest.get("quickPrompts"):
            diagnostics.append(
                Diagnostic(
                    "CODEBUDDY_QUICK_PROMPTS_UNSUPPORTED",
                    DiagnosticSeverity.INFO,
                    "quickPrompts are UI suggestions and were not converted to commands",
                    source_path="quickPrompts",
                )
            )
        status = CompatibilityStatus.DEGRADED if diagnostics else CompatibilityStatus.ADAPTED
        permission_claims = []
        for raw in manifest.get("permissions", []) or []:
            if isinstance(raw, str):
                permission_claims.append(PermissionClaim(raw))
            elif isinstance(raw, dict) and raw.get("capability"):
                permission_claims.append(
                    PermissionClaim(
                        str(raw["capability"]),
                        str(raw.get("reason") or ""),
                        required=bool(raw.get("required", True)),
                    )
                )
        return DerivedPlugin(
            1,
            str(manifest.get("name") or candidate.declared_name or candidate.root.name),
            str(manifest.get("version") or "0.0.0"),
            scalar_description(manifest.get("description")),
            SourceProvenance("local", str(artifact.root), artifact.digest, candidate.relative_root),
            tuple(contributions),
            tuple(permission_claims),
            CompatibilityReport(
                status,
                self.adapter_id,
                self.adapter_version,
                tuple(diagnostics),
            ),
            metadata={
                key: manifest[key]
                for key in ("expertType", "agentName", "teamInfo", "members")
                if key in manifest
            },
        )
