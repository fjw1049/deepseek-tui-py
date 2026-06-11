"""Built-in first-party capability module catalog."""

from __future__ import annotations

from collections.abc import Iterable

from deepseek_tui.config.models import Config
from deepseek_tui.host.module import CapabilityModule, resolve_module_order


class BuiltinModuleCatalog:
    """Fixed catalog for first-party capability modules.

    The catalog intentionally does not discover arbitrary Python packages.
    External extension remains MCP, Skills, and Hooks until the internal module
    API has proven stable.
    """

    def __init__(self, modules: Iterable[CapabilityModule] = ()) -> None:
        self._modules = tuple(modules)

    def enabled_for(self, config: Config) -> tuple[CapabilityModule, ...]:
        enabled = [
            module for module in self._modules if module.descriptor.enabled(config)
        ]
        return resolve_module_order(enabled)


EMPTY_BUILTIN_CATALOG = BuiltinModuleCatalog()


def default_builtin_catalog() -> BuiltinModuleCatalog:
    """Return the first-party builtin module catalog."""
    from deepseek_tui.host.builtin_modules import DEFAULT_BUILTIN_CATALOG

    return DEFAULT_BUILTIN_CATALOG
