"""Builtin runtime API surface contributions from first-party capabilities.

Deprecated: surfaces register through ``host/builtin_modules.py`` and
``collect_builtin_contributions()``. This module remains for tests that need
to populate an isolated registry without full assembly.
"""

from __future__ import annotations

from deepseek_tui.config.models import Config
from deepseek_tui.host.surfaces import RuntimeSurfaceRegistry


def register_builtin_runtime_surfaces(
    registry: RuntimeSurfaceRegistry,
    config: Config,
) -> None:
    """Populate *registry* with the same routes as the default builtin catalog."""
    del config  # catalog surfaces match static HTTP routes regardless of flags
    from deepseek_tui.capabilities import automation, evolution, mcp

    mcp.contribute_runtime_surfaces(registry)
    evolution.contribute_runtime_surfaces(registry)
    automation.contribute_runtime_surfaces(registry)
