from __future__ import annotations

from typing import Protocol

from deepseek_tui.plugins.model import DerivedPlugin
from deepseek_tui.plugins.source import LocalArtifact, PackageCandidate


class PluginAdapter(Protocol):
    adapter_id: str
    adapter_version: int

    def probe(self, candidate: PackageCandidate) -> int: ...

    def derive(
        self,
        artifact: LocalArtifact,
        candidate: PackageCandidate,
    ) -> DerivedPlugin: ...
