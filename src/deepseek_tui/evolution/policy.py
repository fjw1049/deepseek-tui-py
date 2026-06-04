"""Default evolution approval policy."""

from __future__ import annotations

from typing import Literal

from deepseek_tui.config.models import EvolutionConfig
from deepseek_tui.evolution.protocols import ExperienceMutation


class DefaultEvolutionPolicy:
    def __init__(self, config: EvolutionConfig) -> None:
        self._cfg = config

    def decide(
        self, mutation: ExperienceMutation, *, source: str
    ) -> Literal["auto", "propose", "deny"]:
        ledger = self._cfg.ledger
        if not ledger.enabled:
            return "deny"
        if mutation.kind.startswith("memory_curate"):
            return ledger.memory_curate
        if mutation.kind == "skill_patch" and mutation.risk == "low":
            decision = ledger.skill_patch
            if self._cfg.mode == "auto_patch" and decision == "propose":
                return "auto"
            return decision
        if mutation.kind in ("skill_create", "skill_delete", "skill_edit"):
            return ledger.skill_create
        if source == "review" and self._cfg.mode == "suggest":
            return "propose"
        return "propose"
