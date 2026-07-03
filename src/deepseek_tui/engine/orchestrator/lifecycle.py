"""Lifecycle-hook and LSP integration half of the Engine (mixin)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deepseek_tui.integrations.lsp import (
    LSP_MANAGER_KEY,
    LspManager,
    edited_paths_for_tool,
    render_blocks,
)
from deepseek_tui.protocol.messages import Message

if TYPE_CHECKING:
    from deepseek_tui.integrations.hooks import HookContext

logger = logging.getLogger(__name__)


class LifecycleLspMixin:
    """Hook-context construction, lifecycle hooks, and post-edit LSP checks."""

    def _lifecycle_hook_context(
        self,
        *,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        model: str | None = None,
        tool_result: str | None = None,
        tool_success: bool | None = None,
        message: str | None = None,
        error_message: str | None = None,
        previous_mode: str | None = None,
    ) -> HookContext:
        import json

        from deepseek_tui.integrations.hooks import HookContext

        return HookContext(
            tool_name=tool_name,
            tool_args=json.dumps(tool_args) if tool_args is not None else None,
            tool_result=tool_result,
            tool_success=tool_success,
            mode=self.mode,
            previous_mode=previous_mode,
            session_id=self.hook_executor.session_id,
            message=message,
            error_message=error_message,
            workspace=self.tool_context.working_directory,
            model=model or self.default_model,
        )

    async def _run_lifecycle_hook(self, event: str, context: object) -> None:
        if self.hook_executor.has_hooks_for_event(event):
            await self.hook_executor.execute(event, context)  # type: ignore[arg-type]

    async def run_lifecycle_hook(
        self,
        event: str,
        *,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        model: str | None = None,
        tool_result: str | None = None,
        tool_success: bool | None = None,
        message: str | None = None,
        error_message: str | None = None,
        previous_mode: str | None = None,
    ) -> None:
        """Run a lifecycle hook (TUI / app-server entry point)."""
        context = self._lifecycle_hook_context(
            tool_name=tool_name,
            tool_args=tool_args,
            model=model,
            tool_result=tool_result,
            tool_success=tool_success,
            message=message,
            error_message=error_message,
            previous_mode=previous_mode,
        )
        await self._run_lifecycle_hook(event, context)

    def _get_lsp_manager(self) -> LspManager | None:
        """Pull LspManager from ToolContext.metadata (set by ToolRuntime).

        Duck-typed for testability — the engine only needs ``config``
        and ``diagnostics_for``, so any object exposing that shape works.
        """
        manager = self.tool_context.metadata.get(LSP_MANAGER_KEY)
        if manager is None:
            return None
        if not hasattr(manager, "diagnostics_for") or not hasattr(manager, "config"):
            return None
        return manager  # type: ignore[no-any-return]

    async def _run_post_edit_lsp_hook(
        self, tool_name: str, tool_input: dict[str, object]
    ) -> None:
        """Queue diagnostics for files the tool just edited.

        Mirrors Rust ``Engine::run_post_edit_lsp_hook`` (lsp_hooks.rs:80-103).
        Silent failure — a dead LSP server must never block the agent.
        """
        manager = self._get_lsp_manager()
        if manager is None or not manager.config.enabled:
            return
        paths = edited_paths_for_tool(tool_name, tool_input)
        if not paths:
            return
        logger.debug(
            "lsp_post_edit_hook tool=%s paths=%d", tool_name, len(paths)
        )
        workspace = self.tool_context.working_directory
        for path in paths:
            absolute = path if path.is_absolute() else workspace / path
            try:
                content = absolute.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                blocks = await manager.diagnostics_for(
                    absolute, content, self.turn_counter
                )
            except Exception:  # noqa: BLE001 — LSP failure is silent
                continue
            self.pending_lsp_blocks.extend(blocks)

    def _flush_pending_lsp_diagnostics(self, messages: list[Message]) -> None:
        """Render pending blocks into a synthetic user message.

        Mirrors Rust ``Engine::flush_pending_lsp_diagnostics``
        (lsp_hooks.rs:110-127). Attaches the rendered block to
        ``messages`` in place so it rides the next request.
        """
        if not self.pending_lsp_blocks:
            return
        blocks = self.pending_lsp_blocks
        self.pending_lsp_blocks = []
        rendered = render_blocks(blocks)
        if not rendered:
            return
        messages.append(Message.user(rendered))
