"""LSP capability adapter for host runtime assembly."""

from __future__ import annotations

from typing import Any

from deepseek_tui.config.models import Config
from deepseek_tui.host.services import ServiceRegistry, ServiceScope
from deepseek_tui.lsp import LSP_MANAGER_KEY, LspConfig, LspManager


def create_lsp_manager(config: Config, services: ServiceRegistry) -> LspManager | None:
    if not config.lsp.enabled:
        return None
    manager = LspManager(
        LspConfig(
            enabled=True,
            poll_after_edit_ms=config.lsp.poll_after_edit_ms,
            max_diagnostics_per_file=config.lsp.max_diagnostics_per_file,
            include_warnings=config.lsp.include_warnings,
            servers=dict(config.lsp.servers),
        )
    )
    services.add(LspManager, manager, owner="lsp", scope=ServiceScope.PROCESS)
    return manager


def attach_lsp_legacy_bindings(
    manager: LspManager | None,
    *,
    metadata: dict[str, Any],
    services: ServiceRegistry,
) -> None:
    if manager is None:
        return
    metadata[LSP_MANAGER_KEY] = manager
    services.add_named(LSP_MANAGER_KEY, manager, owner="lsp", scope=ServiceScope.PROCESS)


async def shutdown_lsp_manager(manager: LspManager | None) -> None:
    if manager is not None:
        await manager.close_all()
