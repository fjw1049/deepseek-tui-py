"""Config-matrix characterization for catalog tool registration."""

from __future__ import annotations

import pytest

from deepseek_tui.capabilities.toolpacks import catalog_enabled_tool_packs
from deepseek_tui.config.models import Config, EvolutionConfig, FeatureConfig
from deepseek_tui.host.assembler import assemble_registry_only, collect_builtin_contributions
from deepseek_tui.tools.builder import build_default_registry


def _pack_ids(config: Config) -> list[str]:
    assembled = collect_builtin_contributions(config)
    return [pack.id for pack in assembled.tool_packs]


@pytest.mark.parametrize(
    ("config", "absent"),
    [
        (
            Config(features=FeatureConfig(mcp=False, tasks=True, subagents=True)),
            {"mcp_bridge"},
        ),
        (
            Config(features=FeatureConfig(mcp=True, tasks=False, subagents=True)),
            {"tasks", "automation"},
        ),
        (
            Config(features=FeatureConfig(mcp=True, tasks=True, subagents=False)),
            {"subagents"},
        ),
        (
            Config(
                features=FeatureConfig(
                    mcp=True,
                    tasks=True,
                    subagents=True,
                    automations=False,
                )
            ),
            {"automation"},
        ),
        (
            Config(
                features=FeatureConfig(mcp=True, tasks=True, subagents=True),
                evolution=EvolutionConfig(enabled=False),
            ),
            {"evolution_curated", "evolution_procedural"},
        ),
    ],
)
def test_disabled_feature_packs_absent_from_catalog(config: Config, absent: set[str]) -> None:
    registered = set(_pack_ids(config))
    assert absent.isdisjoint(registered)


def test_catalog_pack_ids_match_enabled_helper() -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=True,
            subagents=True,
            mcp=False,
            automations=True,
        ),
        evolution=EvolutionConfig(enabled=True),
    )
    assert _pack_ids(cfg) == [pack.id for pack in catalog_enabled_tool_packs(cfg)]


@pytest.mark.parametrize(
    "config",
    [
        Config(
            features=FeatureConfig(
                tasks=False,
                subagents=False,
                mcp=False,
                automations=False,
            ),
            evolution=EvolutionConfig(enabled=False),
        ),
        Config(
            features=FeatureConfig(
                tasks=True,
                subagents=True,
                mcp=True,
                automations=False,
            ),
            evolution=EvolutionConfig(enabled=True),
        ),
        Config(
            features=FeatureConfig(
                tasks=True,
                subagents=False,
                mcp=True,
                automations=True,
            ),
            evolution=EvolutionConfig(enabled=True),
        ),
    ],
)
def test_assembler_registry_matches_builder_for_config_matrix(config: Config) -> None:
    legacy = build_default_registry(config, mode="agent")
    assembled = assemble_registry_only(config, mode="agent")
    assert legacy.names() == assembled.names()
