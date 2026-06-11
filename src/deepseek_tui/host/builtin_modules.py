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


@dataclass(slots=True)
class _FunctionalModule:
    descriptor: ModuleDescriptor
    _contribute_fn: Callable[[Contributions], None]

    def contribute(self, contributions: Contributions) -> None:
        self._contribute_fn(contributions)


def _contrib_tool_packs(contributions: Contributions) -> None:
    from deepseek_tui.capabilities.toolpacks import default_tool_packs

    for pack in default_tool_packs():
        contributions.add_tool_pack(pack)


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
) -> _FunctionalModule:
    return _FunctionalModule(
        descriptor=ModuleDescriptor(id=module_id, enabled=_always_enabled),
        _contribute_fn=contribute_fn,
    )


def builtin_modules() -> tuple[_FunctionalModule, ...]:
    return (
        _module("builtin.tools", _contrib_tool_packs),
        _module("builtin.core_prompt", _contrib_core_prompts),
        _module("builtin.memory_prompt", _contrib_memory_prompts),
        _module("builtin.skills_prompt", _contrib_skills_prompts),
        _module("builtin.workflow_prompt", _contrib_workflow_prompts),
        _module("builtin.evolution_prompt", _contrib_evolution_prompts),
        _module("builtin.mcp_surfaces", _contrib_mcp_surfaces),
        _module("builtin.evolution_surfaces", _contrib_evolution_surfaces),
        _module("builtin.automation_surfaces", _contrib_automation_surfaces),
    )


DEFAULT_BUILTIN_CATALOG = BuiltinModuleCatalog(builtin_modules())
