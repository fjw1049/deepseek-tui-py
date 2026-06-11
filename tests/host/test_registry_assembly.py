from __future__ import annotations

from deepseek_tui.capabilities.toolpacks import default_tool_packs
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.host.assembler import assemble_registry_only
from deepseek_tui.tools.builder import build_default_registry


def test_default_tool_packs_preserve_builder_order() -> None:
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


def test_build_default_registry_enters_compatible_assembler() -> None:
    cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False))

    registry = build_default_registry(cfg, mode="agent")
    assembled = assemble_registry_only(cfg, mode="agent")

    assert registry.contains("read_file")
    assert registry.contains("edit_file")
    assert assembled.contains("read_file")
    assert assembled.contains("edit_file")


def test_registry_assembly_preserves_plan_mode_filter() -> None:
    cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False))

    registry = build_default_registry(cfg, mode="plan")

    assert registry.contains("read_file")
    assert not registry.contains("edit_file")


def test_registry_assembly_preserves_feature_gates() -> None:
    cfg = Config(
        features=FeatureConfig(
            tasks=True,
            subagents=True,
            mcp=True,
            automations=False,
        )
    )

    registry = build_default_registry(cfg, mode="agent")

    assert registry.contains("task_create")
    assert registry.contains("agent_spawn")
    assert registry.contains("list_mcp_resources")
    assert not registry.contains("automation_create")
