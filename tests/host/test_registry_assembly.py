from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from deepseek_tui.capabilities.toolpacks import catalog_enabled_tool_packs, default_tool_packs
from deepseek_tui.config.models import Config, EvolutionConfig, FeatureConfig
from deepseek_tui.host.assembler import (
    assemble_registry_only,
    build_tool_registry_from_contributions,
    collect_builtin_contributions,
    merge_lifecycle_registries,
    resolve_assembly_prompt_contributors,
)
from deepseek_tui.host.catalog import EMPTY_BUILTIN_CATALOG, BuiltinModuleCatalog
from deepseek_tui.host.contributions import ContributionRegistryError, Contributions
from deepseek_tui.host.lifecycle import FunctionLifecycleObserver
from deepseek_tui.host.module import ModuleDescriptor
from deepseek_tui.host.prompts import FunctionPromptContributor
from deepseek_tui.host.surfaces import RuntimeSurfaceRegistryError
from deepseek_tui.tools.builder import build_default_registry


@dataclass(slots=True)
class _Module:
    descriptor: ModuleDescriptor
    on_contribute: Callable[[Contributions], None]

    def contribute(self, contributions: Contributions) -> None:
        self.on_contribute(contributions)


class _ToolPack:
    def __init__(self, id: str) -> None:
        self.id = id

    def tools(self, _config: object, *, mode: str) -> list[object]:
        return []


def _module(
    id: str,
    on_contribute: Callable[[Contributions], None],
    *,
    requires: tuple[str, ...] = (),
    after: tuple[str, ...] = (),
) -> _Module:
    return _Module(
        descriptor=ModuleDescriptor(
            id=id,
            enabled=lambda _config: True,
            requires=requires,
            after=after,
        ),
        on_contribute=on_contribute,
    )


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


def test_collect_builtin_contributions_empty_catalog_is_noop() -> None:
    assembled = collect_builtin_contributions(
        Config(
            features=FeatureConfig(mcp=False, automations=False, tasks=False),
            evolution=EvolutionConfig(enabled=False),
        ),
        catalog=EMPTY_BUILTIN_CATALOG,
    )

    assert assembled.modules == ()
    assert assembled.tool_packs == ()
    assert assembled.prompt_contributors == ()
    assert assembled.lifecycle.registrations() == ()
    assert assembled.surfaces.routes() == ()


def test_collect_builtin_contributions_default_catalog_registers_tool_packs() -> None:
    cfg = Config()
    assembled = collect_builtin_contributions(cfg)

    assert [pack.id for pack in assembled.tool_packs] == [
        pack.id for pack in catalog_enabled_tool_packs(cfg)
    ]


def test_collect_builtin_contributions_default_catalog_registers_prompts() -> None:
    assembled = collect_builtin_contributions(Config())

    contributor_ids = {contributor.id for contributor in assembled.prompt_contributors}
    assert "project-context" in contributor_ids
    assert "memory-stable" in contributor_ids
    assert "skills" in contributor_ids
    assert "workflow-guidelines" in contributor_ids
    assert "evolution-snapshot" in contributor_ids


def test_resolve_assembly_prompt_contributors_uses_catalog() -> None:
    assembled = collect_builtin_contributions(Config())
    resolved = resolve_assembly_prompt_contributors(assembled)
    assert [contributor.id for contributor in resolved] == [
        contributor.id for contributor in assembled.prompt_contributors
    ]


def test_resolve_assembly_prompt_contributors_falls_back_when_empty() -> None:
    empty = collect_builtin_contributions(Config(), catalog=EMPTY_BUILTIN_CATALOG)
    resolved = resolve_assembly_prompt_contributors(empty)
    assert len(resolved) > 0


def test_collect_builtin_contributions_resolves_module_order() -> None:
    calls: list[str] = []
    first = _module(
        "first",
        lambda contributions: (
            calls.append("first"),
            contributions.lifecycle.add(
                id="first.before_turn",
                owner="first",
                order=200,
                observer=FunctionLifecycleObserver(),
            ),
        ),
    )
    second = _module(
        "second",
        lambda contributions: (
            calls.append("second"),
            contributions.lifecycle.add(
                id="second.before_turn",
                owner="second",
                order=100,
                observer=FunctionLifecycleObserver(),
            ),
        ),
        requires=("first",),
    )

    assembled = collect_builtin_contributions(
        Config(),
        catalog=BuiltinModuleCatalog([second, first]),
    )

    assert [module.descriptor.id for module in assembled.modules] == ["first", "second"]
    assert calls == ["first", "second"]
    assert [registration.id for registration in assembled.lifecycle.registrations()] == [
        "second.before_turn",
        "first.before_turn",
    ]


def test_collect_builtin_contributions_rejects_duplicate_tool_packs() -> None:
    catalog = BuiltinModuleCatalog(
        [
            _module("first", lambda contributions: contributions.add_tool_pack(_ToolPack("core"))),  # type: ignore[arg-type]
            _module("second", lambda contributions: contributions.add_tool_pack(_ToolPack("core"))),  # type: ignore[arg-type]
        ]
    )

    with pytest.raises(ContributionRegistryError, match="tool pack"):
        collect_builtin_contributions(Config(), catalog=catalog)


def test_collect_builtin_contributions_rejects_duplicate_prompt_contributors() -> None:
    catalog = BuiltinModuleCatalog(
        [
            _module(
                "first",
                lambda contributions: contributions.add_prompt_contributor(
                    FunctionPromptContributor("memory", 100, lambda _ctx: "first")
                ),
            ),
            _module(
                "second",
                lambda contributions: contributions.add_prompt_contributor(
                    FunctionPromptContributor("memory", 200, lambda _ctx: "second")
                ),
            ),
        ]
    )

    with pytest.raises(ContributionRegistryError, match="prompt contributor"):
        collect_builtin_contributions(Config(), catalog=catalog)


def test_collect_builtin_contributions_rejects_duplicate_routes() -> None:
    def _add_route(contributions: Contributions) -> None:
        contributions.surfaces.add_route(
            id="route",
            owner="test",
            method="GET",
            path="/v1/test",
            handler=lambda: None,
        )

    catalog = BuiltinModuleCatalog(
        [
            _module("first", _add_route),
            _module("second", _add_route),
        ]
    )

    with pytest.raises(RuntimeSurfaceRegistryError, match="runtime route"):
        collect_builtin_contributions(Config(), catalog=catalog)


def test_build_tool_registry_from_contributions_uses_default_packs_when_empty() -> None:
    cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False))
    assembled = collect_builtin_contributions(
        cfg,
        catalog=BuiltinModuleCatalog([]),
    )

    registry = build_tool_registry_from_contributions(
        assembled,
        cfg,
        mode="agent",
        allow_tool_pack_fallback=True,
    )

    assert registry.contains("read_file")
    assert registry.contains("edit_file")


def test_build_tool_registry_from_contributions_empty_without_fallback() -> None:
    cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False))
    assembled = collect_builtin_contributions(
        cfg,
        catalog=BuiltinModuleCatalog([]),
    )

    registry = build_tool_registry_from_contributions(assembled, cfg, mode="agent")

    assert not registry.names()


def test_merge_lifecycle_registries_skips_engine_owned_ids() -> None:
    from deepseek_tui.host.lifecycle import FunctionLifecycleObserver, LifecycleRegistry

    target = LifecycleRegistry()
    target.add(
        id="memory.before_turn",
        owner="memory",
        order=100,
        observer=FunctionLifecycleObserver(),
    )
    source = LifecycleRegistry()
    source.add(
        id="memory.before_turn",
        owner="other",
        order=50,
        observer=FunctionLifecycleObserver(),
    )
    source.add(
        id="extra.before_turn",
        owner="extra",
        order=150,
        observer=FunctionLifecycleObserver(),
    )

    merge_lifecycle_registries(target, source)

    ids = [registration.id for registration in target.registrations()]
    assert ids == ["memory.before_turn", "extra.before_turn"]
    assert target.registrations()[0].owner == "memory"
