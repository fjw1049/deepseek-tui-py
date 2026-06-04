"""Evolution audit events."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvolutionSuggestedEvent:
    record_id: str
    kind: str
    summary: str
    asset_path: str | None


@dataclass(frozen=True)
class EvolutionAppliedEvent:
    record_id: str
    summary: str


@dataclass(frozen=True)
class EvolutionRejectedEvent:
    record_id: str
    reason: str
