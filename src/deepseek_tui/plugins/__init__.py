"""Stable plugin-host interface.

The legacy implementation still lives in :mod:`deepseek_tui.integrations.plugins`
during the migration.  Callers should depend on this package instead of the
legacy discovery/collector functions directly.
"""

from deepseek_tui.plugins.host import (
    EnablePlugin,
    GcPlugins,
    GrantPlugin,
    InstallPlugin,
    PluginHost,
    PluginInspection,
    PluginSession,
    RemovePlugin,
    RevokePlugin,
    RollbackPlugin,
    TrustPlugin,
    UpdatePlugin,
)

__all__ = [
    "EnablePlugin",
    "GcPlugins",
    "GrantPlugin",
    "InstallPlugin",
    "PluginHost",
    "PluginInspection",
    "PluginSession",
    "RemovePlugin",
    "RevokePlugin",
    "RollbackPlugin",
    "TrustPlugin",
    "UpdatePlugin",
]
