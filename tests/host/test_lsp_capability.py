from __future__ import annotations

import pytest

from deepseek_tui.capabilities.lsp import (
    attach_lsp_legacy_bindings,
    create_lsp_manager,
    shutdown_lsp_manager,
)
from deepseek_tui.config.models import Config, LspSettings
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.lsp import LSP_MANAGER_KEY, LspManager


def test_lsp_capability_skips_when_disabled() -> None:
    services = ServiceRegistry()

    manager = create_lsp_manager(Config(lsp=LspSettings(enabled=False)), services)

    assert manager is None
    assert services.optional(LspManager) is None


def test_lsp_capability_registers_typed_and_legacy_bindings() -> None:
    services = ServiceRegistry()
    metadata: dict[str, object] = {}
    cfg = Config(
        lsp=LspSettings(
            enabled=True,
            poll_after_edit_ms=123,
            max_diagnostics_per_file=7,
            include_warnings=True,
            servers={"python": ["pyright-langserver", "--stdio"]},
        )
    )

    manager = create_lsp_manager(cfg, services)
    attach_lsp_legacy_bindings(manager, metadata=metadata, services=services)

    assert manager is not None
    assert services.require(LspManager) is manager
    assert services.require_named(LSP_MANAGER_KEY) is manager
    assert metadata[LSP_MANAGER_KEY] is manager
    assert manager.config.poll_after_edit_ms == 123
    assert manager.config.max_diagnostics_per_file == 7
    assert manager.config.include_warnings is True
    assert manager.config.servers["python"] == ["pyright-langserver", "--stdio"]


@pytest.mark.asyncio
async def test_lsp_capability_shutdown_closes_manager() -> None:
    services = ServiceRegistry()
    manager = create_lsp_manager(Config(lsp=LspSettings(enabled=True)), services)

    await shutdown_lsp_manager(manager)

    assert manager is not None
