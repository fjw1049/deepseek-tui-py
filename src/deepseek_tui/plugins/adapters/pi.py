from __future__ import annotations

import shutil
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


def _sanitize_plugin_id(value: str, fallback: str) -> str:
    raw = (value or fallback).strip()
    if raw.startswith("@"):
        raw = raw[1:].replace("/", "-")
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in raw)
    return cleaned.strip("-._") or fallback


class PiPackageAdapter:
    adapter_id = "pi-package"
    adapter_version = 2

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
            PermissionClaim("runtime.tool-provider", "Pi extension tools"),
        ]
        scripts = package.get("scripts", {})
        diagnostics = [
            Diagnostic(
                "PI_RUNTIME_ADAPTER_EXPERIMENTAL",
                DiagnosticSeverity.INFO,
                "Pi package was recognized; tools load through the Node sidecar",
            ),
            Diagnostic(
                "PI_WIDGETS_UNSUPPORTED",
                DiagnosticSeverity.WARNING,
                "Pi widgets, keybindings, and custom renderers are not supported",
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
        node_available = shutil.which("node") is not None
        if not node_available:
            diagnostics.append(
                Diagnostic(
                    "PI_NODE_MISSING",
                    DiagnosticSeverity.ERROR,
                    "Node.js is required to activate Pi extensions",
                    remediation="install Node.js and ensure `node` is on PATH",
                )
            )
        ts_entry = False
        for entry in entries:
            if isinstance(entry, str) and entry.rstrip("/").endswith((".ts", ".tsx")):
                ts_entry = True
            elif isinstance(entry, str):
                entry_path = candidate.root / (entry[2:] if entry.startswith("./") else entry)
                if entry_path.is_dir() and not any(
                    (entry_path / name).is_file()
                    for name in ("index.js", "index.mjs", "index.cjs")
                ):
                    if (entry_path / "index.ts").is_file() or list(entry_path.glob("*.ts")):
                        ts_entry = True
        if ts_entry:
            from deepseek_tui.plugins.pi_runtime import node_supports_strip_types

            if node_available and node_supports_strip_types():
                diagnostics.append(
                    Diagnostic(
                        "PI_TYPESCRIPT_STRIP_TYPES",
                        DiagnosticSeverity.WARNING,
                        "TypeScript entrypoints load via Node --experimental-strip-types",
                        remediation="prefer shipping compiled .js/.mjs for production plugins",
                    )
                )
            else:
                diagnostics.append(
                    Diagnostic(
                        "PI_TYPESCRIPT_ENTRYPOINT",
                        DiagnosticSeverity.ERROR,
                        "TypeScript entrypoints require Node.js 22.6+ with "
                        "--experimental-strip-types",
                        remediation="upgrade Node, or ship a .js/.mjs entry",
                    )
                )
        if sys.platform not in {"darwin", "win32", "linux"}:
            diagnostics.append(
                Diagnostic(
                    "PI_PLATFORM_UNSUPPORTED",
                    DiagnosticSeverity.ERROR,
                    f"Pi runtime is unsupported on {sys.platform}",
                )
            )
        status = CompatibilityStatus.ADAPTED
        can_activate = node_available
        if any(item.severity is DiagnosticSeverity.ERROR for item in diagnostics):
            status = CompatibilityStatus.BLOCKED
            can_activate = False
        elif any(item.severity is DiagnosticSeverity.WARNING for item in diagnostics):
            status = CompatibilityStatus.DEGRADED
        plugin_id = _sanitize_plugin_id(
            str(package.get("name") or candidate.root.name),
            candidate.root.name,
        )
        provider = ContributionSpec(
            "runtime.tool-provider",
            plugin_id,
            "Pi extension provider",
            status,
            ActivationMode.ON_DEMAND,
            RiskClass.PRIVILEGED,
            tuple(resources),
            tuple(claims),
            metadata={
                "runtime": "node",
                "node": package.get("engines", {}).get("node", "")
                if isinstance(package.get("engines"), dict)
                else "",
                "entrypoints": entries,
                "peer_dependencies": package.get("peerDependencies", {}),
            },
        )
        return DerivedPlugin(
            1,
            plugin_id,
            str(package.get("version") or "0.0.0"),
            scalar_description(package.get("description")),
            SourceProvenance("local", str(artifact.root), artifact.digest, candidate.relative_root),
            (provider,),
            tuple(claims),
            CompatibilityReport(
                status,
                self.adapter_id,
                self.adapter_version,
                tuple(diagnostics),
                can_install=True,
                can_activate=can_activate,
            ),
            metadata={
                "repository": package.get("repository"),
                "platforms": package.get("os", []),
                "npm_name": package.get("name"),
            },
        )
