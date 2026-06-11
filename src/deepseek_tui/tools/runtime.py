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
from deepseek_tui.execpolicy.sandbox import sandbox_policy_for_mode
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.lsp import LspManager
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.tools.automation_manager import AutomationManager
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.tools.subagent import Mailbox, SubAgentManager
from deepseek_tui.tools.task_manager import TaskManager


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
    _owns_task_manager: bool = True
    _owns_subagent_manager: bool = True
    _owns_mcp_manager: bool = True

    async def __aenter__(self) -> ToolRuntime:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.shutdown()

    async def shutdown(self) -> None:
        from deepseek_tui.capabilities.automation import stop_automation_runtime
        from deepseek_tui.capabilities.lsp import shutdown_lsp_manager
        from deepseek_tui.capabilities.mcp import shutdown_mcp_manager
        from deepseek_tui.capabilities.subagents import shutdown_subagent_runtime
        from deepseek_tui.capabilities.tasks import shutdown_task_manager

        await stop_automation_runtime(
            self._automation_cancel,
            self._automation_scheduler_task,
        )
        await shutdown_subagent_runtime(
            self.subagent_manager,
            self.mailbox,
            owns_manager=self._owns_subagent_manager,
        )
        await shutdown_task_manager(
            self.task_manager,
            owns_manager=self._owns_task_manager,
        )
        await shutdown_mcp_manager(
            self.mcp_manager,
            owns_manager=self._owns_mcp_manager,
        )
        await shutdown_lsp_manager(self.lsp_manager)


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
    shared_task_manager: TaskManager | None = None,
) -> ToolRuntime:
    """Build a fully-wired :class:`ToolRuntime` through host assembly."""
    from deepseek_tui.host.assembler import AssemblyRequest, assemble_tool_runtime

    return await assemble_tool_runtime(
        AssemblyRequest(
            config=config,
            working_directory=working_directory,
            mode=mode,
            policy=policy,
            task_data_dir=task_data_dir,
            subagent_state_path=subagent_state_path,
            mcp_manager=mcp_manager,
            start_mcp=start_mcp,
            automation_data_dir=automation_data_dir,
            automation_tick_interval_secs=automation_tick_interval_secs,
            shared_task_manager=shared_task_manager,
        )
    )


async def _create_tool_runtime_legacy(
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
    shared_task_manager: TaskManager | None = None,
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
    services = ServiceRegistry()

    subagent_manager: SubAgentManager | None = None
    mailbox: Mailbox | None = None

    from deepseek_tui.capabilities.tasks import (
        attach_task_legacy_bindings,
        attach_task_mcp_bridge,
        create_task_manager,
    )

    task_manager, owns_task_manager = await create_task_manager(
        cfg,
        services,
        workspace=workspace,
        task_data_dir=task_data_dir,
        shared_task_manager=shared_task_manager,
        executor_factory=_safe_task_executor,
    )

    from deepseek_tui.capabilities.subagents import create_subagent_manager

    subagent_manager, mailbox = create_subagent_manager(
        cfg,
        services,
        workspace=workspace,
        state_path=subagent_state_path,
        executor_factory=_safe_subagent_executor,
    )

    from deepseek_tui.capabilities.mcp import (
        attach_mcp_legacy_bindings,
        create_mcp_manager,
    )

    mcp, owns_mcp_manager = await create_mcp_manager(
        cfg,
        services,
        provided_manager=mcp_manager,
        start_mcp=start_mcp,
    )
    attach_task_mcp_bridge(task_manager, mcp)

    from deepseek_tui.capabilities.lsp import (
        attach_lsp_legacy_bindings,
        create_lsp_manager,
    )

    lsp = create_lsp_manager(cfg, services)

    registry = build_default_registry(cfg, mode=mode)
    metadata: dict[str, Any] = {}
    attach_task_legacy_bindings(task_manager, metadata=metadata, services=services)
    attach_mcp_legacy_bindings(mcp, metadata=metadata, services=services)
    attach_lsp_legacy_bindings(lsp, metadata=metadata, services=services)

    from deepseek_tui.capabilities.automation import (
        attach_automation_legacy_bindings,
        create_automation_runtime,
    )

    automation_manager, automation_cancel, automation_task = await create_automation_runtime(
        cfg,
        services,
        task_manager=task_manager,
        automation_data_dir=automation_data_dir,
        automation_tick_interval_secs=automation_tick_interval_secs,
    )
    attach_automation_legacy_bindings(
        automation_manager,
        metadata=metadata,
        services=services,
    )

    # Network policy — domain-level allow/deny for outbound HTTP
    network_decider = None
    net_cfg = getattr(cfg, "network_policy", None)
    if net_cfg is not None:
        from deepseek_tui.network.policy import NetworkPolicy, NetworkPolicyDecider

        network_decider = NetworkPolicyDecider(
            policy=NetworkPolicy(
                allow=getattr(net_cfg, "allow", []),
                deny=getattr(net_cfg, "deny", []),
            ),
        )

    context = ToolContext(
        working_directory=workspace,
        trust_mode=getattr(cfg, "trust_mode", False),
        services=services,
        metadata=metadata,
        policy=policy,
        task_manager=task_manager,
        subagent_manager=subagent_manager,
        network_policy=network_decider,
        execution_sandbox_policy=sandbox_policy_for_mode(mode, workspace),
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
        _owns_task_manager=owns_task_manager,
        _owns_subagent_manager=True,
        _owns_mcp_manager=owns_mcp_manager,
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
