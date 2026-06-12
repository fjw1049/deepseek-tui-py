"""Architecture characterization tests for capability assembly."""

from __future__ import annotations

from deepseek_tui.capabilities.toolpacks import catalog_enabled_tool_packs, default_tool_packs
from deepseek_tui.config.models import Config, EvolutionConfig, FeatureConfig
from deepseek_tui.host.assembler import assemble_registry_only, collect_builtin_contributions
from deepseek_tui.tools.builder import build_default_registry


def test_default_tool_catalog_matches_assembler_registry() -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=True,
            subagents=True,
            mcp=True,
            automations=False,
        ),
        evolution=EvolutionConfig(enabled=True),
    )

    legacy = build_default_registry(cfg, mode="agent")
    assembled = assemble_registry_only(cfg, mode="agent")

    assert legacy.names() == assembled.names()


def test_tool_pack_order_is_stable() -> None:
    assert [pack.id for pack in default_tool_packs()] == [
        "core_read",
        "core_write",
        "apply_patch",
        "web",
        "shell",
        "github",
        "mcp_bridge",
        "tasks",
        "subagents",
        "automation",
        "knowledge",
        "engine_intercepted",
        "review",
        "memory",
        "smart_memory",
        "evolution_curated",
        "evolution_procedural",
        "validation",
    ]


def test_memory_prompt_contributors_registered_even_when_memory_disabled_in_config() -> None:
    """Prompt contributors stay registered; contributors no-op without recall input."""
    disabled = collect_builtin_contributions(
        Config(
            features=FeatureConfig(mcp=False, automations=False, tasks=False),
            evolution=EvolutionConfig(enabled=False),
        )
    )
    contributor_ids = {item.id for item in disabled.prompt_contributors}
    assert "memory-stable" in contributor_ids
    assert "user-memory" in contributor_ids
