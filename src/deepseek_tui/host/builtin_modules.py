"""First-party capability modules for the builtin catalog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from deepseek_tui.config.models import Config
from deepseek_tui.host.catalog import BuiltinModuleCatalog
from deepseek_tui.host.contributions import Contributions
from deepseek_tui.host.module import ModuleDescriptor


def _always_enabled(_config: Config) -> bool:
    return True


def _mcp_enabled(config: Config) -> bool:
    return bool(config.features.mcp)


def _tasks_enabled(config: Config) -> bool:
    return bool(config.features.tasks)


def _subagents_enabled(config: Config) -> bool:
    return bool(config.features.subagents)


def _automations_enabled(config: Config) -> bool:
    return bool(config.features.automations and config.features.tasks)


def _smart_memory_enabled(config: Config) -> bool:
    return bool(config.smart_memory_enabled())


def _evolution_curated_enabled(config: Config) -> bool:
    return bool(config.evolution.enabled and config.evolution.curated.enabled)


def _evolution_procedural_enabled(config: Config) -> bool:
    return bool(config.evolution.enabled and config.evolution.procedural.enabled)


def _evolution_surfaces_enabled(config: Config) -> bool:
    return bool(config.evolution.enabled)


@dataclass(slots=True)
class _FunctionalModule:
    descriptor: ModuleDescriptor
    _contribute_fn: Callable[[Contributions], None]

    def contribute(self, contributions: Contributions) -> None:
        self._contribute_fn(contributions)


_EARLY_OPTIONAL_TOOLPACK_MODULE_IDS: tuple[str, ...] = (
    "builtin.toolpack.mcp",
    "builtin.toolpack.tasks",
    "builtin.toolpack.subagents",
    "builtin.toolpack.automation",
)

_LATE_OPTIONAL_TOOLPACK_MODULE_IDS: tuple[str, ...] = (
    "builtin.toolpack.smart_memory",
    "builtin.toolpack.evolution_curated",
    "builtin.toolpack.evolution_procedural",
)


def _contrib_head_tool_packs(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import head_tool_packs

    for pack in head_tool_packs():
        contributions.add_tool_pack(pack)


def _contrib_mcp_tool_pack(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import FunctionToolPack, _mcp_bridge_tools

    contributions.add_tool_pack(FunctionToolPack("mcp_bridge", _mcp_bridge_tools))


def _contrib_tasks_tool_pack(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import FunctionToolPack, _task_tools

    contributions.add_tool_pack(FunctionToolPack("tasks", _task_tools))


def _contrib_subagents_tool_pack(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import FunctionToolPack, _subagent_tools

    contributions.add_tool_pack(FunctionToolPack("subagents", _subagent_tools))


def _contrib_automation_tool_pack(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import FunctionToolPack, _automation_tools

    contributions.add_tool_pack(FunctionToolPack("automation", _automation_tools))


def _contrib_mid_tool_packs(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import tail_tool_packs

    for pack in tail_tool_packs():
        contributions.add_tool_pack(pack)


def _contrib_smart_memory_tool_pack(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import FunctionToolPack, _smart_memory_tools

    contributions.add_tool_pack(FunctionToolPack("smart_memory", _smart_memory_tools))


def _contrib_evolution_curated_tool_pack(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import FunctionToolPack, _evolution_curated_tools

    contributions.add_tool_pack(FunctionToolPack("evolution_curated", _evolution_curated_tools))


def _contrib_evolution_procedural_tool_pack(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import (
        FunctionToolPack,
        _evolution_procedural_tools,
    )

    contributions.add_tool_pack(
        FunctionToolPack("evolution_procedural", _evolution_procedural_tools)
    )


def _contrib_validation_tool_pack(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import validation_tool_pack

    contributions.add_tool_pack(validation_tool_pack())


def _contrib_core_prompts(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.core_prompt import core_prompt_contributors

    for contributor in core_prompt_contributors():
        contributions.add_prompt_contributor(contributor)


def _contrib_memory_prompts(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.memory import memory_prompt_contributors

    for contributor in memory_prompt_contributors():
        contributions.add_prompt_contributor(contributor)


def _contrib_skills_prompts(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.skills import skills_prompt_contributors

    for contributor in skills_prompt_contributors():
        contributions.add_prompt_contributor(contributor)


def _contrib_workflow_prompts(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.workflow import workflow_prompt_contributors

    for contributor in workflow_prompt_contributors():
        contributions.add_prompt_contributor(contributor)


def _contrib_evolution_prompts(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.evolution import evolution_prompt_contributors

    for contributor in evolution_prompt_contributors():
        contributions.add_prompt_contributor(contributor)


def _contrib_mcp_surfaces(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.mcp import contribute_runtime_surfaces

    contribute_runtime_surfaces(contributions.surfaces)


def _contrib_evolution_surfaces(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.evolution import contribute_runtime_surfaces

    contribute_runtime_surfaces(contributions.surfaces)


def _contrib_automation_surfaces(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.automation import contribute_runtime_surfaces

    contribute_runtime_surfaces(contributions.surfaces)


def _module(
    module_id: str,
    contribute_fn: Callable[[Contributions], None],
    *,
    enabled: Callable[[Config], bool] | None = None,
    requires: tuple[str, ...] = (),
    after: tuple[str, ...] = (),
) -> _FunctionalModule:
    return _FunctionalModule(
        descriptor=ModuleDescriptor(
            id=module_id,
            enabled=enabled or _always_enabled,
            requires=requires,
            after=after,
        ),
        _contribute_fn=contribute_fn,
    )


def builtin_modules() -> tuple[_FunctionalModule, ...]:
    return (
        _module("builtin.toolpack.core", _contrib_head_tool_packs),
        _module(
            "builtin.toolpack.mcp",
            _contrib_mcp_tool_pack,
            enabled=_mcp_enabled,
            after=("builtin.toolpack.core",),
        ),
        _module(
            "builtin.toolpack.tasks",
            _contrib_tasks_tool_pack,
            enabled=_tasks_enabled,
            after=("builtin.toolpack.core",),
        ),
        _module(
            "builtin.toolpack.subagents",
            _contrib_subagents_tool_pack,
            enabled=_subagents_enabled,
            after=("builtin.toolpack.core",),
        ),
        _module(
            "builtin.toolpack.automation",
            _contrib_automation_tool_pack,
            enabled=_automations_enabled,
            requires=("builtin.toolpack.tasks",),
            after=("builtin.toolpack.core",),
        ),
        _module(
            "builtin.toolpack.mid",
            _contrib_mid_tool_packs,
            after=_EARLY_OPTIONAL_TOOLPACK_MODULE_IDS,
        ),
        _module(
            "builtin.toolpack.smart_memory",
            _contrib_smart_memory_tool_pack,
            enabled=_smart_memory_enabled,
            after=("builtin.toolpack.mid",),
        ),
        _module(
            "builtin.toolpack.evolution_curated",
            _contrib_evolution_curated_tool_pack,
            enabled=_evolution_curated_enabled,
            after=("builtin.toolpack.mid",),
        ),
        _module(
            "builtin.toolpack.evolution_procedural",
            _contrib_evolution_procedural_tool_pack,
            enabled=_evolution_procedural_enabled,
            after=("builtin.toolpack.mid",),
        ),
        _module(
            "builtin.toolpack.validation",
            _contrib_validation_tool_pack,
            after=_LATE_OPTIONAL_TOOLPACK_MODULE_IDS,
        ),
        _module("builtin.core_prompt", _contrib_core_prompts),
        _module("builtin.memory", _contrib_memory_prompts),
        _module("builtin.skills", _contrib_skills_prompts),
        _module("builtin.workflow", _contrib_workflow_prompts),
        _module("builtin.evolution", _contrib_evolution_prompts),
        _module(
            "builtin.mcp_surfaces",
            _contrib_mcp_surfaces,
            enabled=_mcp_enabled,
        ),
        _module(
            "builtin.evolution_surfaces",
            _contrib_evolution_surfaces,
            enabled=_evolution_surfaces_enabled,
        ),
        _module(
            "builtin.automation_surfaces",
            _contrib_automation_surfaces,
            enabled=_automations_enabled,
            requires=("builtin.toolpack.tasks",),
        ),
    )


DEFAULT_BUILTIN_CATALOG = BuiltinModuleCatalog(builtin_modules())
