"""Contribution container for first-party capability modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from deepseek_tui.host.lifecycle import LifecycleRegistry
from deepseek_tui.host.prompts import PromptContributor
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.host.surfaces import RuntimeSurfaceRegistry

if TYPE_CHECKING:
    from deepseek_tui.host.toolpacks import ToolPack


class ContributionRegistryError(RuntimeError):
    """Raised when capability contributions conflict."""


@dataclass(slots=True)
class Contributions:
    """Host-owned collection point for module contributions.

    Module adapters describe their pieces here; the assembler remains
    responsible for deciding when those pieces are started, invoked, or exposed.
    """

    services: ServiceRegistry = field(default_factory=ServiceRegistry)
    lifecycle: LifecycleRegistry = field(default_factory=LifecycleRegistry)
    surfaces: RuntimeSurfaceRegistry = field(default_factory=RuntimeSurfaceRegistry)
    _tool_packs: dict[str, ToolPack] = field(default_factory=dict)
    _prompt_contributors: dict[str, PromptContributor] = field(default_factory=dict)

    def add_tool_pack(self, pack: ToolPack) -> None:
        if pack.id in self._tool_packs:
            raise ContributionRegistryError(
                f"tool pack {pack.id!r} already contributed"
            )
        self._tool_packs[pack.id] = pack

    def tool_packs(self) -> tuple[ToolPack, ...]:
        return tuple(self._tool_packs.values())

    def add_prompt_contributor(self, contributor: PromptContributor) -> None:
        if contributor.id in self._prompt_contributors:
            raise ContributionRegistryError(
                f"prompt contributor {contributor.id!r} already contributed"
            )
        self._prompt_contributors[contributor.id] = contributor

    def prompt_contributors(self) -> tuple[PromptContributor, ...]:
        return tuple(
            sorted(self._prompt_contributors.values(), key=lambda item: item.order)
        )
