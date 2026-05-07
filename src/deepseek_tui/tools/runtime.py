"""Runtime bundle — wire the registry, managers, and ToolContext together.

This solves the "each tool wired in isolation" problem: :func:`create_tool_runtime`
is the **one** entry point the engine / tests / CLI go through to get a
fully-operational ToolContext with:

- TaskManager (Stage 3.1) started and attached
- SubAgentManager (Stage 3.2) attached with its Mailbox
- McpManager (Stage 4.3) attached via ``ToolContext.metadata`` so the
  mcp_tools dispatchers can reach it
- Policy (Stage 2.5) attached
- workspace rooted at the caller-supplied cwd

Call :meth:`ToolRuntime.shutdown` (or use it as an async context manager) to
drain managers cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import Config
from deepseek_tui.execpolicy.policy import Policy
from deepseek_tui.mcp.manager import McpManager
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

    async def __aenter__(self) -> ToolRuntime:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.shutdown()

    async def shutdown(self) -> None:
        if self.mailbox is not None:
            self.mailbox.close()
        if self.subagent_manager is not None:
            await self.subagent_manager.shutdown()
        if self.task_manager is not None:
            await self.task_manager.shutdown()
        if self.mcp_manager is not None:
            await self.mcp_manager.stop_all()


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
        task_manager = TaskManager(task_cfg)
        await task_manager.start()

    if cfg.features.subagents:
        mailbox = Mailbox()
        state_path = subagent_state_path or (workspace / ".deepseek" / "subagents.v1.json")
        subagent_manager = SubAgentManager(
            workspace=workspace,
            state_path=state_path,
            mailbox=mailbox,
        )

    mcp: McpManager | None = None
    if mcp_manager is not None:
        mcp = mcp_manager
    elif cfg.features.mcp:
        mcp = await _build_mcp_manager(cfg)
    if mcp is not None and start_mcp:
        await mcp.start_all()

    registry = build_default_registry(cfg, mode=mode)
    metadata: dict[str, Any] = {}
    if mcp is not None:
        from deepseek_tui.tools.mcp_tools import MCP_MANAGER_KEY

        metadata[MCP_MANAGER_KEY] = mcp

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
    )


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
