"""Tool runtime — execution orchestration, parallelism, spillover.

Consolidates runtime.py, parallel_tool.py, spillover.py.
"""

from __future__ import annotations



# Runtime bundle — wire the registry, managers, and ToolContext together.
#
# This solves the "each tool wired in isolation" problem: :func:`create_tool_runtime`
# is the **one** entry point the engine / tests / CLI go through to get a
# fully-operational ToolContext with:
#
# - TaskManager (Stage 3.1) started and attached
# - SubAgentManager (Stage 3.2) attached with its Mailbox
# - McpManager (Stage 4.3) attached via ``ToolContext.metadata`` so the
#   mcp_tools dispatchers can reach it
# - AutomationManager + scheduler loop (2026-05-15) attached when
#   ``features.automations`` is enabled
# - Policy (Stage 2.5) attached
# - workspace rooted at the caller-supplied cwd
#
# Call :meth:`ToolRuntime.shutdown` (or use it as an async context manager) to
# drain managers cleanly.
#
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import Config
from deepseek_tui.policy.exec_policy import Policy
from deepseek_tui.integrations.lsp import LSP_MANAGER_KEY, LspConfig, LspManager
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.tools.automation import (
    AutomationManager,
    default_automations_dir,
)
from deepseek_tui.tools.automation import (
    AutomationSchedulerConfig,
    run_scheduler_loop,
)
from deepseek_tui.tools.automation import AUTOMATION_MANAGER_KEY
from deepseek_tui.policy.sandbox import sandbox_policy_for_mode
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.registry import ToolRegistry
from typing import TYPE_CHECKING as _TC2
if _TC2:
    from deepseek_tui.tools.subagent import Mailbox, SubAgentManager
from deepseek_tui.tools.task import (
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
    _owns_task_manager: bool = True
    _owns_subagent_manager: bool = True
    _owns_mcp_manager: bool = True

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
        if self._owns_subagent_manager and self.subagent_manager is not None:
            await self.subagent_manager.shutdown()
        if self._owns_task_manager and self.task_manager is not None:
            await self.task_manager.shutdown()
        if self._owns_mcp_manager and self.mcp_manager is not None:
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
    from deepseek_tui.tools.registry import build_default_registry

    cfg = config or Config()
    workspace = (working_directory or Path.cwd()).resolve()

    task_manager: TaskManager | None = None
    subagent_manager: SubAgentManager | None = None
    mailbox: Mailbox | None = None
    owns_task_manager = True

    if shared_task_manager is not None:
        task_manager = shared_task_manager
        owns_task_manager = False
    elif cfg.features.tasks:
        data_dir = task_data_dir if task_data_dir is not None else default_tasks_dir()
        task_cfg = TaskManagerConfig(
            data_dir=data_dir,
            default_workspace=workspace,
            allow_shell=cfg.allow_shell,
            trust_mode=getattr(cfg, "trust_mode", False),
            worker_count=1,
        )
        task_exec = _safe_task_executor()
        task_manager = TaskManager(task_cfg, executor=task_exec)
        await task_manager.start()

    if cfg.features.subagents:
        from deepseek_tui.tools.subagent import Mailbox, SubAgentManager
        mailbox = Mailbox()
        state_path = subagent_state_path or (workspace / ".deepseek" / "subagents.v1.json")
        subagent_exec = _safe_subagent_executor()
        max_agents = min(
            20,
            cfg.max_subagents or cfg.subagents.max_concurrent or 10,
        )
        subagent_manager = SubAgentManager(
            workspace=workspace,
            max_agents=max_agents,
            state_path=state_path,
            mailbox=mailbox,
            executor=subagent_exec,
            default_model=cfg.subagents.default_model or cfg.default_text_model or "deepseek-chat",
        )

    mcp: McpManager | None = None
    owns_mcp_manager = True
    if mcp_manager is not None:
        mcp = mcp_manager
        owns_mcp_manager = False
    elif cfg.features.mcp:
        mcp = await _build_mcp_manager(cfg)
    if mcp is not None and start_mcp:
        await mcp.start_all(fail_on_required=True)
    if task_manager is not None and mcp is not None:
        task_manager._shared_mcp_manager = mcp  # noqa: SLF001 — executor reuse

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
        from deepseek_tui.tools.mcp import MCP_MANAGER_KEY

        metadata[MCP_MANAGER_KEY] = mcp
    if lsp is not None:
        metadata[LSP_MANAGER_KEY] = lsp

    automation_manager: AutomationManager | None = None
    automation_cancel: asyncio.Event | None = None
    automation_task: asyncio.Task[None] | None = None
    if cfg.features.automations:
        # Hard dependency: automations have no executor of their own —
        # every fire ends up calling ``TaskManager.add_task``. Fail
        # fast at construction time rather than letting the LLM call
        # ``automation_run`` and discover the missing dependency at
        # runtime. Mirrors Rust ``registry.rs::with_runtime_task_tools``
        # which registers task + automation tools together.
        if not cfg.features.tasks:
            raise ValueError(
                "features.automations requires features.tasks=True "
                "(automations fire by enqueueing tasks)"
            )
        automation_root = (
            automation_data_dir
            if automation_data_dir is not None
            else default_automations_dir()
        )
        automation_manager = AutomationManager.open(automation_root)
        metadata[AUTOMATION_MANAGER_KEY] = automation_manager
        # AutomationRunTool reaches the TaskManager through the same
        # context.metadata bag — Rust does this through ``runtime``.
        # The ``features.tasks`` guard above guarantees task_manager is
        # not None here.
        assert task_manager is not None
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

    if task_manager is not None:
        metadata["task_manager"] = task_manager

    # Network policy — domain-level allow/deny for outbound HTTP
    network_decider = None
    net_cfg = getattr(cfg, "network_policy", None)
    if net_cfg is not None:
        from deepseek_tui.policy.network import NetworkPolicy, NetworkPolicyDecider

        network_decider = NetworkPolicyDecider(
            policy=NetworkPolicy(
                allow=getattr(net_cfg, "allow", []),
                deny=getattr(net_cfg, "deny", []),
            ),
        )

    context = ToolContext(
        working_directory=workspace,
        trust_mode=getattr(cfg, "trust_mode", False),
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
        from deepseek_tui.tools.task import get_real_task_executor

        return get_real_task_executor()
    from deepseek_tui.tools.task import _stub_executor

    return _stub_executor


def _safe_subagent_executor() -> Any:
    """Return real executor if API key available, else stub."""
    if _has_api_key():
        from deepseek_tui.tools.subagent import get_real_subagent_executor

        return get_real_subagent_executor()
    from deepseek_tui.tools.subagent import _stub_executor

    return _stub_executor


async def _build_mcp_manager(cfg: Config) -> McpManager:
    """Load ``mcp_config_path`` and return an :class:`McpManager`.

    Missing / malformed config → empty manager (best-effort, matching
    Rust ``McpManager::default`` behavior when config is absent).
    """
    from deepseek_tui.mcp.config import load_mcp_config

    try:
        path = cfg.mcp_config_path.expanduser()
        servers = load_mcp_config(path)
    except (OSError, ValueError):
        servers = []
    return McpManager(servers, config_path=path)


# MultiToolUseParallelTool — expands a batch of read-only tool calls.
#
# Mirrors `crates/tui/src/tools/parallel.rs`.
#
# The model may emit a single ``multi_tool_use.parallel`` tool call whose
# ``tool_uses`` array contains multiple sub-calls.  The Engine intercepts
# this name and fans out the sub-calls concurrently (read-only only).
# The ToolSpec itself always raises — it must never be dispatched directly.
#
from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext

MULTI_TOOL_PARALLEL_NAME = "multi_tool_use.parallel"


class MultiToolUseParallelTool(ToolSpec):
    def name(self) -> str:
        return MULTI_TOOL_PARALLEL_NAME

    def description(self) -> str:
        return (
            "Run multiple read-only tools in parallel. "
            "Must be handled by the engine — direct execution is an error."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "tool_uses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {"type": "string"},
                            "parameters": {"type": "object"},
                        },
                        "required": ["recipient_name", "parameters"],
                    },
                }
            },
            "required": ["tool_uses"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        raise ToolError("multi_tool_use.parallel must be handled by the engine")


# Tool-output spillover writer (#422).
#
# Mirrors ``docs/DeepSeek-TUI-main/crates/tui/src/tools/truncate.rs``.
#
import logging
import os
import time
from dataclasses import replace
from pathlib import Path

from deepseek_tui.config.paths import user_tool_outputs_dir
from deepseek_tui.tools.registry import ToolResult

logger = logging.getLogger(__name__)

SPILLOVER_DIR_NAME = "tool_outputs"
SPILLOVER_THRESHOLD_BYTES = 100 * 1024
SPILLOVER_HEAD_BYTES = 32 * 1024
SPILLOVER_MAX_AGE_SECS = 7 * 24 * 60 * 60

_TEST_SPILLOVER_ROOT: Path | None = None


def spillover_root() -> Path | None:
    """Resolve ``~/.deepseek/tool_outputs/`` (or test override)."""
    if _TEST_SPILLOVER_ROOT is not None:
        return _TEST_SPILLOVER_ROOT
    try:
        return user_tool_outputs_dir()
    except Exception:  # noqa: BLE001
        return None


def set_test_spillover_root(root: Path | None) -> Path | None:
    """Override spillover root for tests."""
    global _TEST_SPILLOVER_ROOT
    previous = _TEST_SPILLOVER_ROOT
    _TEST_SPILLOVER_ROOT = root
    return previous


def sanitise_id(tool_id: str) -> str | None:
    """Keep ASCII alphanumerics, ``-``, ``_``; reject empty."""
    cleaned = "".join(
        ch for ch in tool_id if ch.isascii() and (ch.isalnum() or ch in "-_")
    )
    return cleaned or None


def spillover_path(tool_id: str) -> Path | None:
    root = spillover_root()
    safe = sanitise_id(tool_id)
    if root is None or safe is None:
        return None
    return root / f"{safe}.txt"


def write_spillover(tool_id: str, content: str) -> Path:
    path = spillover_path(tool_id)
    if path is None:
        raise OSError("could not resolve spillover path")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path


def prune_older_than(max_age_secs: float = SPILLOVER_MAX_AGE_SECS) -> int:
    """Delete spillover files older than *max_age_secs*. Non-fatal."""
    root = spillover_root()
    if root is None or not root.is_dir():
        return 0
    cutoff = time.time() - max_age_secs
    pruned = 0
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                pruned += 1
        except OSError as err:
            logger.warning("spillover prune skipped %s: %s", entry, err)
    return pruned


def _utf8_head(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    cut = min(max_bytes, len(encoded))
    while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
        cut -= 1
    return encoded[:cut].decode("utf-8")


def maybe_spillover(
    tool_id: str,
    content: str,
    *,
    threshold: int = SPILLOVER_THRESHOLD_BYTES,
    head_bytes: int = SPILLOVER_HEAD_BYTES,
) -> tuple[str, Path] | None:
    if len(content.encode("utf-8")) <= threshold:
        return None
    path = write_spillover(tool_id, content)
    head = _utf8_head(content, head_bytes)
    return head, path


def apply_spillover(result: ToolResult, tool_id: str) -> ToolResult:
    """Spill large successful tool results to disk; shrink inline content.

    Mirrors Rust ``apply_spillover`` (truncate.rs:229). Failures are logged
    and the original result is returned unchanged.
    """
    if not result.success:
        return result
    content = result.content or ""
    if len(content.encode("utf-8")) <= SPILLOVER_THRESHOLD_BYTES:
        return result

    total = len(content.encode("utf-8"))
    try:
        pair = maybe_spillover(tool_id, content)
    except OSError as err:
        logger.warning("spillover write failed tool_id=%s: %s", tool_id, err)
        return result
    if pair is None:
        return result

    head, path = pair
    path_str = str(path)
    head_kib = len(head.encode("utf-8")) // 1024
    total_kib = total // 1024
    footer = (
        f"\n\n[Output truncated: {head_kib} KiB of {total_kib} KiB shown. "
        f"Full output saved to {path_str}. Use "
        f"`retrieve_tool_result ref={tool_id} mode=tail` or "
        f"`retrieve_tool_result ref={tool_id} mode=query query=<text>` "
        f"if you need the elided output.]"
    )
    metadata = dict(result.metadata)
    metadata["spillover_path"] = path_str
    return replace(result, content=head + footer, metadata=metadata)
