from __future__ import annotations

import pytest

from deepseek_tui.capabilities.lsp import (
    attach_lsp_bindings,
    create_lsp_manager,
    lsp_tool_observer,
    shutdown_lsp_manager,
)
from deepseek_tui.config.models import Config, LspSettings
from deepseek_tui.host.lifecycle import AfterToolContext
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.lsp import LSP_MANAGER_KEY, DiagnosticBlock, LspConfig, LspManager


class _FakeLspManager:
    def __init__(self) -> None:
        self.config = LspConfig(enabled=True)
        self.calls: list[tuple[object, str, int]] = []

    async def diagnostics_for(
        self,
        path: object,
        content: str,
        turn_counter: int,
    ) -> list[DiagnosticBlock]:
        self.calls.append((path, content, turn_counter))
        return [DiagnosticBlock(path=str(path), diagnostics=[])]


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
    attach_lsp_bindings(manager, services=services)

    assert manager is not None
    assert services.require(LspManager) is manager
    assert services.require_named(LSP_MANAGER_KEY) is manager
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


@pytest.mark.asyncio
async def test_lsp_tool_observer_adds_diagnostics_for_successful_edit(tmp_path) -> None:
    edited = tmp_path / "example.py"
    edited.write_text("print('hello')\n", encoding="utf-8")
    manager = _FakeLspManager()
    pending: list[object] = []
    observer = lsp_tool_observer(
        manager=lambda: manager,
        workspace=lambda: tmp_path,
        turn_counter=lambda: 7,
        add_pending_blocks=pending.extend,
    )

    await observer.after_tool(
        AfterToolContext(
            tool_call_id="call-1",
            tool_name="edit_file",
            arguments={"path": str(edited), "old": "", "new": ""},
            success=True,
            result=object(),
            metadata={},
            services=ServiceRegistry(),
        )
    )

    assert len(manager.calls) == 1
    assert manager.calls[0][1] == "print('hello')\n"
    assert manager.calls[0][2] == 7
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_lsp_tool_observer_skips_failed_tools(tmp_path) -> None:
    manager = _FakeLspManager()
    pending: list[object] = []
    observer = lsp_tool_observer(
        manager=lambda: manager,
        workspace=lambda: tmp_path,
        turn_counter=lambda: 7,
        add_pending_blocks=pending.extend,
    )

    await observer.after_tool(
        AfterToolContext(
            tool_call_id="call-1",
            tool_name="edit_file",
            arguments={"path": str(tmp_path / "example.py")},
            success=False,
            result=object(),
            metadata={},
            services=ServiceRegistry(),
        )
    )

    assert manager.calls == []
    assert pending == []
