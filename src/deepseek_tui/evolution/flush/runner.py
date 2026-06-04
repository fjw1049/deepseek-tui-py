"""Evolution flush runner — reuses review with flush prompt."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.client.base import LLMClient
from deepseek_tui.evolution.protocols import EvolutionBackend, ExperienceMutation
from deepseek_tui.evolution.review.runner import run_evolution_review
from deepseek_tui.post_turn.evidence import TurnEvidence


async def run_evolution_flush(
    client: LLMClient,
    model: str,
    evidence: TurnEvidence,
    backends: list[EvolutionBackend],
    *,
    ledger: object | None = None,
    max_steps: int = 8,
    workspace: Path | None = None,
    curated_store: object | None = None,
    skill_store: object | None = None,
) -> list[ExperienceMutation]:
    return await run_evolution_review(
        client,
        model=model,
        evidence=evidence,
        backends=backends,
        ledger=ledger,
        review_memory=True,
        review_skill=True,
        flush_mode=True,
        max_steps=max_steps,
        workspace=workspace,
        curated_store=curated_store,
        skill_store=skill_store,
    )
