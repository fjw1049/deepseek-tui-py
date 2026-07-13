from __future__ import annotations

from deepseek_tui.plugins.adapters.common import markdown_metadata, resource_ref, scalar_description
from deepseek_tui.plugins.model import (
    ActivationMode,
    CompatibilityReport,
    CompatibilityStatus,
    ContributionSpec,
    DerivedPlugin,
    RiskClass,
    SourceProvenance,
)
from deepseek_tui.plugins.source import LocalArtifact, PackageCandidate


class BareSkillAdapter:
    adapter_id = "bare-skill"
    adapter_version = 1

    def probe(self, candidate: PackageCandidate) -> int:
        return 90 if (candidate.root / "SKILL.md").is_file() else 0

    def derive(self, artifact: LocalArtifact, candidate: PackageCandidate) -> DerivedPlugin:
        skill = candidate.root / "SKILL.md"
        metadata, _ = markdown_metadata(skill)
        name = str(metadata.get("name") or candidate.root.name)
        contribution = ContributionSpec(
            "prompt.skill",
            name,
            scalar_description(metadata.get("description")),
            CompatibilityStatus.NATIVE,
            ActivationMode.ON_DEMAND,
            RiskClass.CONTENT,
            (resource_ref(candidate, skill),),
        )
        return DerivedPlugin(
            1,
            name,
            str(metadata.get("version") or "0.0.0"),
            contribution.summary,
            SourceProvenance("local", str(artifact.root), artifact.digest, candidate.relative_root),
            (contribution,),
            (),
            CompatibilityReport(
                CompatibilityStatus.NATIVE,
                self.adapter_id,
                self.adapter_version,
            ),
        )
