"""Experience evolution metadata keys for ToolContext."""

from __future__ import annotations

from typing import Any

CURATED_MEMORY_STORE_KEY = "curated_memory_store"
SKILL_STORE_KEY = "skill_store"
EVOLUTION_LEDGER_KEY = "evolution_ledger"
POST_TURN_ORCHESTRATOR_KEY = "post_turn_orchestrator"
TURN_EVIDENCE_KEY = "turn_evidence"
TURN_EVIDENCE_FACTORY_KEY = "turn_evidence_factory"


def resolve_turn_evidence(metadata: dict[str, Any]) -> Any | None:
    """Return current TurnEvidence from metadata, preferring the live factory."""
    factory = metadata.get(TURN_EVIDENCE_FACTORY_KEY)
    if callable(factory):
        return factory()
    return metadata.get(TURN_EVIDENCE_KEY)
