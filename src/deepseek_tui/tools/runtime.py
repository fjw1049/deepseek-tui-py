"""Runtime bundle — wire the registry, managers, and ToolContext together.

This solves the "each tool wired in isolation" problem: :func:`create_tool_runtime`
is the **one** entry point the engine / tests / CLI go through to get a
fully-operational ToolContext with:

- TaskManager (Stage 3.1) started and attached
- SubAgentManager (Stage 3.2) attached with its Mailbox
- McpManager (Stage 4.3) attached via ``ToolContext.metadata`` so the
  mcp_tools dispatchers can reach it
- AutomationManager + scheduler loop (2026-05-15) attached when
  ``features.automations`` is enabled
- Policy (Stage 2.5) attached
- workspace rooted at the caller-supplied cwd

Call :meth:`ToolRuntime.shutdown` (or use it as an async context manager) to
drain managers cleanly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import Config
from deepseek_tui.execpolicy.policy import Policy
from deepseek_tui.lsp import LSP_MANAGER_KEY, LspConfig, LspManager
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.tools.automation_manager import (
    AutomationManager,
    default_automations_dir,
)
from deepseek_tui.tools.automation_scheduler import (
    AutomationSchedulerConfig,
    run_scheduler_loop,
)
from deepseek_tui.tools.automation_tools import AUTOMATION_MANAGER_KEY
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.tools.subagent import Mailbox, SubAgentManager
from deepseek_tui.tools.task_manager import (
    TaskManager,
    TaskManagerConfig,
    default_tasks_dir,
)


@dataclass(slots=True)
class ToolRuntime:
    """Full tool runtime — registry + context + started managers.

    Use :func:`create_tool_runtime` to build one. The caller owns the
    lifecycle and must call :meth:`shutdown` (or use ``async with``).
    """

    context: ToolContext
    registry: ToolRegistry
    task_manager: TaskManager | None
    subagent_manager: SubAgentManager | None
    mailbox: Mailbox | None
    mcp_manager: McpManager | None
    lsp_manager: LspManager | None
    automation_manager: AutomationManager | None = None
    _automation_scheduler_task: asyncio.Task[None] | None = None
    _automation_cancel: asyncio.Event | None = field(default=None)

    async def __aenter__(self) -> ToolRuntime:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.shutdown()

    async def shutdown(self) -> None:
        if self._automation_cancel is not None:
            self._automation_cancel.set()
        if self._automation_scheduler_task is not None:
            try:
                await asyncio.wait_for(
                    self._automation_scheduler_task, timeout=5.0
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._automation_scheduler_task.cancel()
            except Exception:  # noqa: BLE001
                pass
        if self.mailbox is not None:
            self.mailbox.close()
        if self.subagent_manager is not None:
            await self.subagent_manager.shutdown()
        if self.task_manager is not None:
            await self.task_manager.shutdown()
        if self.mcp_manager is not None:
            await self.mcp_manager.stop_all()
        if self.lsp_manager is not None:
            await self.lsp_manager.close_all()


async def create_tool_runtime(
    *,
    config: Config | None = None,
    working_directory: Path | None = None,
    mode: str = "agent",
    policy: Policy | None = None,
    task_data_dir: Path | None = None,
    subagent_state_path: Path | None = None,
    mcp_manager: McpManager | None = None,
    start_mcp: bool = False,
    automation_data_dir: Path | None = None,
    automation_tick_interval_secs: float = 15.0,
) -> ToolRuntime:
    """Build a fully-wired :class:`ToolRuntime`.

    - ``config.features.tasks`` gates TaskManager construction + startup
    - ``config.features.subagents`` gates SubAgentManager construction
    - ``config.features.mcp`` gates McpManager construction; the caller
      may pre-build one (for tests) via ``mcp_manager=...``. Pass
      ``start_mcp=True`` to eagerly start all configured servers.
    - policy is attached verbatim (caller may build one via
      ``execpolicy.Policy.default()``)
    """
    from deepseek_tui.tools.builder import build_default_registry

    cfg = config or Config()
    workspace = (working_directory or Path.cwd()).resolve()

    task_manager: TaskManager | None = None
    subagent_manager: SubAgentManager | None = None
    mailbox: Mailbox | None = None

    if cfg.features.tasks:
        data_dir = task_data_dir if task_data_dir is not None else default_tasks_dir()
        task_cfg = TaskManagerConfig(
            data_dir=data_dir,
            default_workspace=workspace,
            allow_shell=cfg.allow_shell,
            trust_mode=getattr(cfg, "trust_mode", False),
        )
        task_exec = _safe_task_executor()
        task_manager = TaskManager(task_cfg, executor=task_exec)
        await task_manager.start()

    if cfg.features.subagents:
        mailbox = Mailbox()
        state_path = subagent_state_path or (workspace / ".deepseek" / "subagents.v1.json")
        subagent_exec = _safe_subagent_executor()
        subagent_manager = SubAgentManager(
            workspace=workspace,
            state_path=state_path,
            mailbox=mailbox,
            executor=subagent_exec,
        )

    mcp: McpManager | None = None
    if mcp_manager is not None:
        mcp = mcp_manager
    elif cfg.features.mcp:
        mcp = await _build_mcp_manager(cfg)
    if mcp is not None and start_mcp:
        await mcp.start_all()

    lsp: LspManager | None = None
    if cfg.lsp.enabled:
        lsp = LspManager(
            LspConfig(
                enabled=True,
                poll_after_edit_ms=cfg.lsp.poll_after_edit_ms,
                max_diagnostics_per_file=cfg.lsp.max_diagnostics_per_file,
                include_warnings=cfg.lsp.include_warnings,
                servers=dict(cfg.lsp.servers),
            )
        )

    registry = build_default_registry(cfg, mode=mode)
    metadata: dict[str, Any] = {}
    if mcp is not None:
        from deepseek_tui.tools.mcp_tools import MCP_MANAGER_KEY

        metadata[MCP_MANAGER_KEY] = mcp
    if lsp is not None:
        metadata[LSP_MANAGER_KEY] = lsp

    automation_manager: AutomationManager | None = None
    automation_cancel: asyncio.Event | None = None
    automation_task: asyncio.Task[None] | None = None
    if cfg.features.automations:
        automation_root = (
            automation_data_dir
            if automation_data_dir is not None
            else default_automations_dir()
        )
        automation_manager = AutomationManager.open(automation_root)
        metadata[AUTOMATION_MANAGER_KEY] = automation_manager
        # AutomationRunTool reaches the TaskManager through the same
        # context.metadata bag — Rust does this through ``runtime``.
        if task_manager is not None:
            metadata["task_manager"] = task_manager
            automation_cancel = asyncio.Event()
            automation_task = asyncio.create_task(
                run_scheduler_loop(
                    automation_manager,
                    task_manager,
                    automation_cancel,
                    AutomationSchedulerConfig(
                        tick_interval_secs=automation_tick_interval_secs,
                    ),
                ),
                name="automation-scheduler",
            )

    context = ToolContext(
        working_directory=workspace,
        trust_mode=getattr(cfg, "trust_mode", False),
        metadata=metadata,
        policy=policy,
        task_manager=task_manager,
        subagent_manager=subagent_manager,
    )

    return ToolRuntime(
        context=context,
        registry=registry,
        task_manager=task_manager,
        subagent_manager=subagent_manager,
        mailbox=mailbox,
        mcp_manager=mcp,
        lsp_manager=lsp,
        automation_manager=automation_manager,
        _automation_scheduler_task=automation_task,
        _automation_cancel=automation_cancel,
    )


def _has_api_key() -> bool:
    """Check if a DeepSeek API key is available for real executors."""
    import os

    if os.environ.get("DEEPSEEK_API_KEY"):
        return True
    try:
        from deepseek_tui.config.loader import ConfigLoader

        cfg = ConfigLoader().load()
        if cfg.api_key:
            return True
        pc = cfg.effective_provider_config()
        if pc.api_key:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _safe_task_executor() -> Any:
    """Return real executor if API key available, else stub."""
    if _has_api_key():
        from deepseek_tui.tools.task_manager import get_real_task_executor

        return get_real_task_executor()
    from deepseek_tui.tools.task_manager import _stub_executor

    return _stub_executor


def _safe_subagent_executor() -> Any:
    """Return real executor if API key available, else stub."""
    if _has_api_key():
        from deepseek_tui.tools.subagent.manager import get_real_subagent_executor

        return get_real_subagent_executor()
    from deepseek_tui.tools.subagent.manager import _stub_executor

    return _stub_executor


async def _build_mcp_manager(cfg: Config) -> McpManager:
    """Load ``mcp_config_path`` and return an :class:`McpManager`.

    Missing / malformed config → empty manager (best-effort, matching
    Rust ``McpManager::default`` behavior when config is absent).
    """
    from deepseek_tui.mcp.loader import load_mcp_config

    try:
        path = cfg.mcp_config_path.expanduser()
        servers = load_mcp_config(path)
    except (OSError, ValueError):
        servers = []
    return McpManager(servers)
