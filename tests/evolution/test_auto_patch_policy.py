from deepseek_tui.config.models import EvolutionConfig, EvolutionLedgerConfig
from deepseek_tui.evolution.policy import DefaultEvolutionPolicy
from deepseek_tui.evolution.protocols import ExperienceMutation


def _skill_patch() -> ExperienceMutation:
    return ExperienceMutation(kind="skill_patch", payload={}, risk="low")


def test_auto_patch_upgrades_propose_to_auto() -> None:
    cfg = EvolutionConfig(mode="auto_patch", ledger=EvolutionLedgerConfig(skill_patch="propose"))
    decision = DefaultEvolutionPolicy(cfg).decide(_skill_patch(), source="review")
    assert decision == "auto"


def test_auto_patch_respects_deny() -> None:
    cfg = EvolutionConfig(mode="auto_patch", ledger=EvolutionLedgerConfig(skill_patch="deny"))
    decision = DefaultEvolutionPolicy(cfg).decide(_skill_patch(), source="review")
    assert decision == "deny"


def test_auto_patch_keeps_auto_when_configured() -> None:
    cfg = EvolutionConfig(mode="auto_patch", ledger=EvolutionLedgerConfig(skill_patch="auto"))
    decision = DefaultEvolutionPolicy(cfg).decide(_skill_patch(), source="review")
    assert decision == "auto"


def test_suggest_mode_uses_ledger_skill_patch() -> None:
    cfg = EvolutionConfig(mode="suggest", ledger=EvolutionLedgerConfig(skill_patch="propose"))
    decision = DefaultEvolutionPolicy(cfg).decide(_skill_patch(), source="main_tool")
    assert decision == "propose"
