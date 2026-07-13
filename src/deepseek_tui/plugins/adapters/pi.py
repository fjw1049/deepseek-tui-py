from __future__ import annotations

import sys

from deepseek_tui.plugins.adapters.common import read_json, resource_ref, scalar_description
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


class PiPackageAdapter:
    adapter_id = "pi-package"
    adapter_version = 1

    def probe(self, candidate: PackageCandidate) -> int:
        package_json = candidate.root / "package.json"
        if not package_json.is_file():
            return 0
        try:
            package = read_json(package_json)
        except ValueError:
            return 0
        pi = package.get("pi")
        return 120 if isinstance(pi, dict) and pi.get("extensions") else 0

    def derive(self, artifact: LocalArtifact, candidate: PackageCandidate) -> DerivedPlugin:
        package = read_json(candidate.root / "package.json")
        pi = package["pi"]
        entries = pi.get("extensions", [])
        if isinstance(entries, str):
            entries = [entries]
        resources = []
        for entry in entries:
            if not isinstance(entry, str):
                continue
            normalized = entry[2:] if entry.startswith("./") else entry
            path = artifact.resolve(candidate.root, normalized)
            if path.exists():
                resources.append(resource_ref(candidate, path))

        claims = [
            PermissionClaim("process.spawn", "isolated Node sidecar"),
            PermissionClaim("filesystem.read", "extension package and configuration"),
        ]
        scripts = package.get("scripts", {})
        diagnostics = [
            Diagnostic(
                "PI_RUNTIME_ADAPTER_EXPERIMENTAL",
                DiagnosticSeverity.INFO,
                "Pi package was recognized through its extension manifest",
            ),
            Diagnostic(
                "PI_SIDECAR_UNAVAILABLE",
                DiagnosticSeverity.ERROR,
                "Pi Node sidecar is not implemented yet",
                remediation="install remains safe; activation is blocked",
            ),
        ]
        if isinstance(scripts, dict) and scripts.get("postinstall"):
            claims.append(PermissionClaim("package.install-scripts", "package postinstall script"))
            diagnostics.append(
                Diagnostic(
                    "PI_INSTALL_SCRIPT_REQUIRES_GRANT",
                    DiagnosticSeverity.WARNING,
                    "package declares a postinstall script; it was not executed",
                    source_path="scripts.postinstall",
                )
            )
        if sys.platform not in {"darwin", "win32"}:
            diagnostics.append(
                Diagnostic(
                    "PI_PLATFORM_UNSUPPORTED",
                    DiagnosticSeverity.ERROR,
                    f"Pi computer-use style runtime is unsupported on {sys.platform}",
                )
            )
        provider = ContributionSpec(
            "runtime.tool-provider",
            str(package.get("name") or candidate.root.name),
            "Pi extension provider",
            CompatibilityStatus.BLOCKED,
            ActivationMode.ON_DEMAND,
            RiskClass.PRIVILEGED,
            tuple(resources),
            tuple(claims),
            metadata={
                "runtime": "node",
                "node": package.get("engines", {}).get("node", ""),
                "entrypoints": entries,
                "peer_dependencies": package.get("peerDependencies", {}),
            },
        )
        return DerivedPlugin(
            1,
            str(package.get("name") or candidate.root.name),
            str(package.get("version") or "0.0.0"),
            scalar_description(package.get("description")),
            SourceProvenance("local", str(artifact.root), artifact.digest, candidate.relative_root),
            (provider,),
            tuple(claims),
            CompatibilityReport(
                CompatibilityStatus.BLOCKED,
                self.adapter_id,
                self.adapter_version,
                tuple(diagnostics),
                can_install=False,
                can_activate=False,
            ),
            metadata={
                "repository": package.get("repository"),
                "platforms": package.get("os", []),
            },
        )
