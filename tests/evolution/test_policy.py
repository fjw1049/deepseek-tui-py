from deepseek_tui.config.models import EvolutionConfig
from deepseek_tui.evolution.policy import DefaultEvolutionPolicy
from deepseek_tui.evolution.protocols import ExperienceMutation


def test_policy_memory_curate_auto_by_default() -> None:
    policy = DefaultEvolutionPolicy(EvolutionConfig())
    decision = policy.decide(
        ExperienceMutation(kind="memory_curate_add", payload={}, risk="low"),
        source="main_tool",
    )
    assert decision == "auto"


def test_policy_skill_create_propose_by_default() -> None:
    policy = DefaultEvolutionPolicy(EvolutionConfig())
    decision = policy.decide(
        ExperienceMutation(kind="skill_create", payload={}, risk="medium"),
        source="main_tool",
    )
    assert decision == "propose"
