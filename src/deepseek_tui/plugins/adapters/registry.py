from __future__ import annotations

from pathlib import Path

from deepseek_tui.plugins.adapters.bare_skill import BareSkillAdapter
from deepseek_tui.plugins.adapters.claude import ClaudePluginAdapter
from deepseek_tui.plugins.adapters.codebuddy import CodeBuddyPluginAdapter
from deepseek_tui.plugins.adapters.pi import PiPackageAdapter
from deepseek_tui.plugins.model import (
    CompatibilityReport,
    CompatibilityStatus,
    DerivedPlugin,
    Diagnostic,
    DiagnosticSeverity,
    SourceProvenance,
)
from deepseek_tui.plugins.source import LocalArtifact, locate_packages

_ADAPTERS = (
    PiPackageAdapter(),
    CodeBuddyPluginAdapter(),
    ClaudePluginAdapter(),
    BareSkillAdapter(),
)


def inspect_local_source(
    source: str | Path,
) -> tuple[tuple[DerivedPlugin, ...], tuple[Diagnostic, ...]]:
    artifact = LocalArtifact(Path(source))
    candidates, locator_diagnostics = locate_packages(artifact)
    packages: list[DerivedPlugin] = []
    diagnostics = list(locator_diagnostics)
    for candidate in candidates:
        remote_source = candidate.marketplace_entry.get("source")
        if isinstance(remote_source, dict):
            packages.append(
                DerivedPlugin(
                    1,
                    candidate.declared_name or "remote-plugin",
                    str(candidate.marketplace_entry.get("version") or "0.0.0"),
                    str(candidate.marketplace_entry.get("description") or ""),
                    SourceProvenance(
                        str(remote_source.get("source") or "remote"),
                        str(remote_source.get("url") or remote_source),
                        "",
                        str(remote_source.get("path") or "."),
                    ),
                    (),
                    (),
                    CompatibilityReport(
                        CompatibilityStatus.BLOCKED,
                        "source-resolver",
                        1,
                        (
                            Diagnostic(
                                "REMOTE_MARKETPLACE_SOURCE_NOT_FETCHED",
                                DiagnosticSeverity.INFO,
                                "remote package must be fetched before format inspection",
                            ),
                        ),
                        can_install=(remote_source.get("source") == "git-subdir"),
                        can_activate=False,
                    ),
                    metadata={
                        "marketplace": candidate.marketplace_entry,
                        "catalog": {
                            "kind": "local-marketplace",
                            "locator": str(artifact.root),
                            "digest": artifact.digest,
                            "relative_root": candidate.relative_root,
                        },
                    },
                )
            )
            continue
        scores = [(adapter.probe(candidate), adapter) for adapter in _ADAPTERS]
        top = max((score for score, _ in scores), default=0)
        winners = [adapter for score, adapter in scores if score == top and score > 0]
        if not winners:
            diagnostics.append(
                Diagnostic(
                    "PLUGIN_ADAPTER_NOT_FOUND",
                    DiagnosticSeverity.ERROR,
                    f"no adapter recognized package at {candidate.relative_root}",
                    source_path=candidate.relative_root,
                )
            )
            continue
        if len(winners) > 1:
            names = ", ".join(adapter.adapter_id for adapter in winners)
            diagnostics.append(
                Diagnostic(
                    "AMBIGUOUS_PLUGIN_ADAPTER",
                    DiagnosticSeverity.ERROR,
                    f"ambiguous plugin format at {candidate.relative_root}: {names}",
                    source_path=candidate.relative_root,
                    remediation="disambiguate the package layout or select an adapter explicitly",
                )
            )
            continue
        try:
            packages.append(winners[0].derive(artifact, candidate))
        except Exception as exc:  # noqa: BLE001 - one bad plugin must not abort discovery
            diagnostics.append(
                Diagnostic(
                    "PLUGIN_DERIVE_FAILED",
                    DiagnosticSeverity.ERROR,
                    f"adapter {winners[0].adapter_id} could not derive "
                    f"{candidate.relative_root}: {exc}",
                    source_path=candidate.relative_root,
                    remediation="inspect the plugin manifest or frontmatter syntax",
                )
            )

    by_id: dict[str, list[DerivedPlugin]] = {}
    for package in packages:
        by_id.setdefault(package.plugin_id.lower(), []).append(package)
    for plugin_id, collisions in by_id.items():
        if len(collisions) > 1:
            diagnostics.append(
                Diagnostic(
                    "PLUGIN_ID_COLLISION",
                    DiagnosticSeverity.ERROR,
                    f"multiple candidates declare plugin id {plugin_id!r}",
                    remediation="select one candidate explicitly; automatic merge is disabled",
                )
            )
    return tuple(packages), tuple(diagnostics)
