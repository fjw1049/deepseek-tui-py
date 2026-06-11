"""Capability module descriptors and ordering helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from deepseek_tui.config.models import Config

if TYPE_CHECKING:
    from deepseek_tui.host.contributions import Contributions


class ModuleOrderError(RuntimeError):
    """Raised when module dependencies cannot be resolved."""


@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    id: str
    enabled: Callable[[Config], bool]
    requires: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


class CapabilityModule(Protocol):
    descriptor: ModuleDescriptor

    def contribute(self, contributions: Contributions) -> None: ...


@dataclass(slots=True)
class OrderedModule:
    id: str
    descriptor: ModuleDescriptor
    module: CapabilityModule
    dependencies: tuple[str, ...] = field(default_factory=tuple)


def resolve_module_order(modules: Sequence[CapabilityModule]) -> tuple[CapabilityModule, ...]:
    """Return modules in dependency order without invoking their contributions."""
    by_id: dict[str, CapabilityModule] = {}
    for module in modules:
        module_id = module.descriptor.id
        if module_id in by_id:
            raise ModuleOrderError(f"duplicate capability module id {module_id!r}")
        by_id[module_id] = module

    ordered: list[CapabilityModule] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(module_id: str, trail: Iterable[str]) -> None:
        if module_id in permanent:
            return
        if module_id in temporary:
            cycle = " -> ".join([*trail, module_id])
            raise ModuleOrderError(f"capability module dependency cycle: {cycle}")
        module = by_id.get(module_id)
        if module is None:
            raise ModuleOrderError(f"capability module {module_id!r} is required but missing")
        temporary.add(module_id)
        descriptor = module.descriptor
        for dependency in (*descriptor.requires, *descriptor.after):
            if dependency in by_id:
                visit(dependency, [*trail, module_id])
            elif dependency in descriptor.requires:
                raise ModuleOrderError(
                    f"capability module {module_id!r} requires missing module {dependency!r}"
                )
        temporary.remove(module_id)
        permanent.add(module_id)
        ordered.append(module)

    for module in modules:
        visit(module.descriptor.id, [])
    return tuple(ordered)
