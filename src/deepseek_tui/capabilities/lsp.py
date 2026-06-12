"""LSP capability adapter for host runtime assembly."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from deepseek_tui.config.models import Config
from deepseek_tui.host.services import ServiceRegistry, ServiceScope
from deepseek_tui.lsp import LSP_MANAGER_KEY, LspConfig, LspManager, edited_paths_for_tool

logger = logging.getLogger(__name__)


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


def attach_lsp_bindings(
    manager: LspManager | None,
    *,
    services: ServiceRegistry,
) -> None:
    if manager is None:
        return
    if services.optional_named(LSP_MANAGER_KEY) is None:
        services.add_named(LSP_MANAGER_KEY, manager, owner="lsp", scope=ServiceScope.PROCESS)


def lsp_manager_from_context(
    *,
    services: ServiceRegistry,
) -> object | None:
    manager = services.optional(LspManager)
    if manager is not None:
        return cast(object | None, manager)
    return services.optional_named(LSP_MANAGER_KEY)


@dataclass(slots=True)
class LspToolObserver:
    manager: Callable[[], object | None]
    workspace: Callable[[], Path]
    turn_counter: Callable[[], int]
    add_pending_blocks: Callable[[list[object]], None]

    async def after_tool(self, context: object) -> None:
        if not context.success:  # type: ignore[attr-defined]
            return
        manager = self.manager()
        if manager is None or not getattr(getattr(manager, "config", None), "enabled", False):
            return
        try:
            paths = edited_paths_for_tool(
                context.tool_name,  # type: ignore[attr-defined]
                context.arguments,  # type: ignore[attr-defined]
            )
        except Exception:  # noqa: BLE001
            return
        if not paths:
            return
        logger.debug(
            "lsp_post_edit_hook tool=%s paths=%d",
            context.tool_name,  # type: ignore[attr-defined]
            len(paths),
        )
        workspace = self.workspace()
        pending: list[object] = []
        for rel in paths:
            absolute = (workspace / rel).resolve()
            try:
                content = absolute.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                blocks = await manager.diagnostics_for(  # type: ignore[attr-defined]
                    absolute,
                    content,
                    self.turn_counter(),
                )
            except Exception:  # noqa: BLE001 - LSP failure is silent
                continue
            pending.extend(blocks)
        if pending:
            self.add_pending_blocks(pending)


def lsp_tool_observer(
    *,
    manager: Callable[[], object | None],
    workspace: Callable[[], Path],
    turn_counter: Callable[[], int],
    add_pending_blocks: Callable[[list[object]], None],
) -> LspToolObserver:
    return LspToolObserver(
        manager=manager,
        workspace=workspace,
        turn_counter=turn_counter,
        add_pending_blocks=add_pending_blocks,
    )


async def shutdown_lsp_manager(manager: LspManager | None) -> None:
    if manager is not None:
        await manager.close_all()


def register_engine_lifecycle_observer(access: object, registry: object) -> None:
    """Register the LSP after-tool lifecycle observer once."""
    from deepseek_tui.host.lifecycle import lifecycle_observer_registered

    if lifecycle_observer_registered(registry, "lsp.after_tool"):  # type: ignore[arg-type]
        return

    tool_context = access.tool_context  # type: ignore[attr-defined]

    registry.add(  # type: ignore[attr-defined]
        id="lsp.after_tool",
        owner="lsp",
        order=50,
        observer=lsp_tool_observer(
            manager=lambda: lsp_manager_from_context(
                services=tool_context.services,
            ),
            workspace=lambda: tool_context.working_directory,
            turn_counter=access.turn_counter,  # type: ignore[attr-defined]
            add_pending_blocks=access.pending_lsp_blocks.extend,  # type: ignore[attr-defined]
        ),
    )
