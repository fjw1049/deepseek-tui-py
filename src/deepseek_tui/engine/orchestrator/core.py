"""Engine core — construction, turn loop, and conversation orchestration.

Tool dispatch, maintenance, and lifecycle/LSP methods live in sibling mixins.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.capacity import (
    CapacityController,
    CapacityControllerConfig,
    CompactionConfig,
    run_error_escalation_checkpoint,
    run_post_tool_checkpoint,
    run_pre_request_checkpoint,
    should_compact,
)
from deepseek_tui.engine.context import WorkingSet
from deepseek_tui.engine.cycle import (
    CycleConfig,
    SessionActivityCoordinator,
)
from deepseek_tui.engine.dispatch import (
    should_force_update_plan_first,
)
from deepseek_tui.engine.events import (
    AgentRoundCompleteEvent,
    ErrorEvent,
    PluginMountEvent,
    SessionEndedEvent,
    SessionStartedEvent,
    StatusEvent,
    ToolCallEvent,
    ToolResultEvent,
    GoalUpdatedEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.engine.handle import (
    PROCESS_BACKGROUND_DONE_KIND,
    SUBAGENT_BACKGROUND_DONE_KIND,
    ApprovalHandler,
    AutoApprovalHandler,
    CancelRequestOp,
    EngineHandle,
    SendMessageOp,
)
from deepseek_tui.engine.orchestrator.helpers import (
    FOCUS_MCP_BASE,
    FOCUS_PLUGIN_BASE,
    FOCUS_SKILL_BASE,
    _assistant_preface_text,
    _detect_focus_mcp,
    _detect_focus_skill,
    _detect_plugin_mount,
    _resolve_app_mode,
    _strip_focus_prefix,
    _strip_plugin_mount,
)
from deepseek_tui.engine.orchestrator.lifecycle import LifecycleLspMixin
from deepseek_tui.engine.orchestrator.maintenance import SessionMaintenanceMixin
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.engine.prompts import (
    build_system_prompt,
)
from deepseek_tui.engine.tools import (
    PLAN_MODE_TOOL_ALLOWLIST,
    build_model_tool_catalog,
)
from deepseek_tui.engine.turn import TurnLoop, TurnResult, prepare_turn_for_model
from deepseek_tui.integrations.lsp import DiagnosticBlock
from deepseek_tui.protocol.messages import Message, MessageOrigin, MessageRequest
from deepseek_tui.tools.approval import ApprovalCache, ExecPolicyEngine
from deepseek_tui.tools.registry import ToolContext, ToolRegistry
from deepseek_tui.tools.subagent import SubAgentCompletion
from deepseek_tui.utils import bind_turn

if TYPE_CHECKING:
    from deepseek_tui.tools.runtime import ToolRuntime

logger = logging.getLogger(__name__)

# Backstop for the checklist turn-end gate. Progress-based release already
# bounds it in the normal case; this only catches a model that closes one item
# and opens another every time it is blocked.
_CHECKLIST_GATE_MAX_FIRES = 3

# Same backstop for turn_end ("Stop") hooks. Unlike the checklist gate there is
# no progress signal to release on, so a hook that blocks unconditionally used
# to spin to the round-trip limit — re-sending the whole context every round.
# Hooks still receive ``stop_hook_active`` so a well-written one yields first.
_STOP_HOOK_MAX_FIRES = 3


def _path_under(path: Path, root: Path) -> bool:
    """Whether ``path`` is inside ``root`` (both resolved)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _index_command_proxies(plugin_index: dict[str, dict[str, Any]]) -> list[Any]:
    """Build lightweight command proxies from the lockfile index.

    Each proxy has the attributes ``render_plugin_components_context``
    accesses (``plugin``, ``name``, ``qualified``, ``argument_hint``,
    ``description``). ``qualified`` is reconstructed as ``<plugin>:<name>``;
    ``argument_hint`` is not in the index and defaults to empty.
    """
    from types import SimpleNamespace

    out: list[Any] = []
    for plugin_name, idx in plugin_index.items():
        for c in idx.get("commands", []):
            name = c.get("name", "")
            out.append(
                SimpleNamespace(
                    plugin=plugin_name,
                    name=name,
                    qualified=f"{plugin_name}:{name}",
                    argument_hint="",
                    description=c.get("description", ""),
                )
            )
    return out


def _index_agent_proxies(plugin_index: dict[str, dict[str, Any]]) -> list[Any]:
    """Build lightweight agent proxies from the lockfile index."""
    from types import SimpleNamespace

    out: list[Any] = []
    for plugin_name, idx in plugin_index.items():
        for a in idx.get("agents", []):
            out.append(
                SimpleNamespace(
                    plugin=plugin_name,
                    name=a.get("name", ""),
                    description=a.get("description", ""),
                )
            )
    return out


def _register_plugin_agent(registry: dict[str, Any], agent: Any) -> None:
    """Register under ``plugin:name`` and bare ``name`` (first wins on bare)."""
    name = (getattr(agent, "name", None) or "").strip()
    if not name:
        return
    plugin = (getattr(agent, "plugin", None) or "").strip()
    bare = name.lower()
    if plugin:
        registry[f"{plugin}:{name}".lower()] = agent
    if bare not in registry:
        registry[bare] = agent


def _unique_plugin_agents(registry: dict[str, Any]) -> list[Any]:
    """Deduplicate registry values (bare + qualified keys share one object)."""
    seen: set[int] = set()
    out: list[Any] = []
    for agent in registry.values():
        key = id(agent)
        if key in seen:
            continue
        seen.add(key)
        out.append(agent)
    return out


def _agent_index_from_plugin_index(
    plugin_index: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Map agent name / ``plugin:name`` → owning plugin (for deferred activate)."""
    agent_index: dict[str, str] = {}
    for pname, pidx in plugin_index.items():
        for a in pidx.get("agents", []):
            aname = (a.get("name") or "").strip().lower()
            if not aname:
                continue
            agent_index[f"{pname.lower()}:{aname}"] = pname
            agent_index.setdefault(aname, pname)
    return agent_index


def _index_rule_proxies(plugin_index: dict[str, dict[str, Any]]) -> list[Any]:
    """Build lightweight rule proxies from the lockfile index.

    Includes both ``always_apply`` and scenario (``always_apply: false``)
    rules. ``body`` is empty -- unmounted rendering only uses ``name`` +
    ``description``.
    """
    from types import SimpleNamespace

    out: list[Any] = []
    for plugin_name, idx in plugin_index.items():
        for r in idx.get("rules", []):
            out.append(
                SimpleNamespace(
                    plugin=plugin_name,
                    name=r.get("name", ""),
                    description=r.get("description", ""),
                    always_apply=r.get("always_apply", True),
                    body="",
                )
            )
    return out


# In-turn wait for a background shell to finish. Shorter than the sub-agent
# handoff budget on purpose: the command already spent up to
# EXEC_MAX_TIMEOUT_MS (600s) in the foreground before it was re-homed.
SHELL_HANDOFF_TIMEOUT_SECS = 120.0


def _format_process_done(payload: dict[str, Any]) -> str:
    process_id = payload.get("process_id") or ""
    command = payload.get("command") or ""
    returncode = payload.get("returncode")
    output = str(payload.get("output") or "").strip()
    lines = [
        "Background shell process finished.",
        f"process_id: {process_id}",
        f"command: {command}",
        f"exit_code: {returncode}",
    ]
    if output:
        lines.extend(["", output])
    lines.extend(
        [
            "",
            f'Full output is still available via task_output(process_id="{process_id}").',
        ]
    )
    return "\n".join(lines)


class Engine(ToolExecutionMixin, SessionMaintenanceMixin, LifecycleLspMixin):
    def __init__(
        self,
        handle: EngineHandle,
        client: LLMClient,
        default_model: str = "deepseek-chat",
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
        exec_policy: ExecPolicyEngine | None = None,
        approval_handler: ApprovalHandler | None = None,
        max_tool_round_trips: int = 200,
        tool_runtime: ToolRuntime | None = None,
        compaction_config: CompactionConfig | None = None,
        skill_registry: object | None = None,
        default_reasoning_effort: str | None = None,
        default_temperature: float | None = None,
        default_top_p: float | None = None,
        default_extra_body: dict[str, Any] | None = None,
        hook_executor: object | None = None,
    ) -> None:
        self.handle = handle
        self.client = client
        self.default_model = default_model
        from deepseek_tui.engine.usage_ledger import TurnUsageLedger

        self.turn_usage_ledger = TurnUsageLedger()
        self._goal_accounted_output_tokens = 0
        # When a full runtime is supplied, it wins — unpack registry + context
        # from it so managers stay paired with the context they own.
        if tool_runtime is not None:
            self.tool_registry = tool_runtime.registry
            # Shared runtimes have a fixed working_directory from process start.
            # Each Engine must honour its own workspace (from the thread) so that
            # the system prompt and tool execution use the correct project root.
            if tool_context is not None:
                self.tool_context = tool_context
            else:
                self.tool_context = tool_runtime.context
        else:
            self.tool_registry = tool_registry or ToolRegistry()
            self.tool_context = tool_context or ToolContext(working_directory=Path.cwd())
        self.tool_runtime = tool_runtime
        self._owns_tool_runtime = tool_runtime is None
        # True when Engine.create built a per-engine SubAgentManager (shared
        # runtime case) — shutdown_session must then reap it here because the
        # shared ToolRuntime.shutdown() never sees it.
        self._owns_subagent_manager = False
        # Ensure the registry dispatcher can see the context (Stage 3
        # managers are attached on the context, not the registry).
        self.tool_registry.set_context(self.tool_context)
        self.exec_policy = exec_policy or ExecPolicyEngine()
        self.approval_handler = approval_handler or AutoApprovalHandler()
        self.max_tool_round_trips = max_tool_round_trips
        self.mode: str = "agent"
        # Reply language from config.ui.locale (Workbench settings). Default zh.
        self.reply_locale: str = "zh"
        self.compaction_config = compaction_config or CompactionConfig()
        self.capacity_controller = CapacityController(config=CapacityControllerConfig())
        self.session_messages: list[Message] = []
        # Last rewrite-bridge text (for iterative re-compaction). The live
        # bridge is a leading user message in session_messages — never the
        # system prompt (KV prefix cache).
        self._compaction_summary_prompt: str | None = None
        self.turn_loop = TurnLoop(client, compact_fn=self._emergency_compact)
        # Cumulative session cost (USD / CNY), accumulated per turn from
        # the DeepSeek usage payload via the pricing module. The footer
        # reads these to render the cost chip and the ``/cost`` slash
        # command sources from the same fields.
        self.session_cost_usd: float = 0.0
        self.session_cost_cny: float = 0.0
        # 2026-05-15: cumulative cache hit/miss tokens across the whole
        # session. Intentional deviation from the footer cache spans, which
        # display only the most recent turn's cache-hit tokens
        # — i.e. the most recent turn. DeepSeek's prefix cache means
        # every turn after the first has a near-100% hit ratio, so the
        # per-turn number is constant ~99% and carries no information.
        # The session-cumulative ratio actually shows the user how much
        # prompt-bytes they have saved.
        # See HANDOVER §九 ``cache_chip.2026-05-15 cumulative``.
        self.session_cache_hit_total: int = 0
        self.session_cache_miss_total: int = 0
        # Previous round's per-unit request digests, for attributing a prefix
        # cache miss to whatever rewrote history. See ``_log_prefix_break``.
        self._prefix_digests: list[str] = []
        # Stage 4.4 post-edit LSP diagnostics — pending diagnostic blocks.
        self.pending_lsp_blocks: list[DiagnosticBlock] = []
        self.turn_counter = 0
        # Last real input_tokens reported by the provider (from the final
        # stream of the previous turn). Used as the primary signal for
        # should_compact: it is the exact billed input, zero estimation
        # error. Zero before the first turn completes — callers fall back
        # to the char-based estimate. See HANDOVER §compaction tuning.
        self.last_real_input_tokens: int = 0
        # Auto-compaction failure cooldown: rounds remaining before we try
        # auto-compaction again after a failed attempt. Without this, a
        # failing compaction (e.g. summary model returns empty) would retry
        # 3x every round for the entire turn — pure waste. Set to N rounds
        # on failure, decremented each round, blocks auto-compaction while > 0.
        self._compact_cooldown_rounds: int = 0
        # mtime of the last handoff reminder injected into messages (not
        # system). Re-inject only when the file is new or rewritten.
        self._handoff_injected_mtime: float | None = None
        # Session-start git snapshot is injected once, on the first real
        # user turn (Claude Code's gitStatus pattern).
        self._git_snapshot_injected: bool = False
        # Stage 3.next.1 approval cache — fingerprints repeat tool calls
        # so an APPROVED_SESSION grant doesn't have to re-prompt.
        self.approval_cache = ApprovalCache()
        # Skills integration — renders available skills into system prompt
        self.skill_registry = skill_registry
        # Skill 聚焦模式：per-turn 工具白名单。None = 全量（默认）；置位时
        # ``_get_tools_with_mcp`` 只返回交集。由 ``_handle_send_message_inner``
        # 在 try/finally 中设置与复位，不跨 turn 保留。
        self._focus_tool_whitelist: frozenset[str] | None = None
        # Server-level allowlist paired with _focus_tool_whitelist. When a
        # plugin mount / MCP focus covers a lazy (undiscovered) MCP server,
        # tool names are unknown; the filter falls back to matching the
        # tool's server via McpManager._match_configured_server (prefix-based,
        # discovery-independent). frozenset() when focus active but no MCP
        # server is whitelisted; None when no focus active at all.
        self._focus_allowed_servers: frozenset[str] | None = None
        # 插件挂载（@plugin:name）：会话级持续态，与单轮聚焦不同不在 turn 末
        # 复位。挂载后每轮开头把它折算进 ``_focus_tool_whitelist`` —— 模型只
        # 看到「只读底座 + 按插件 permissions 的写工具 + 该插件的 skill/MCP
        # 工具」。用户显式打 `/skill` 或 `@mcp` 时该轮让位（前缀优先）。
        self._active_plugin: object | None = None
        # Main-thread persona (PluginAgent) activated by the mounted
        # plugin's settings.json ``defaultAgent``. Its body is appended to
        # the plugin context block while mounted; cleared on unmount.
        self._scenario_agent: Any | None = None
        # Frozen plugin view for this Engine.  Source discovery, contribution
        # assembly, and future format adapters live behind this seam.
        self.plugin_session: Any | None = None
        self._session_mcp_manager: Any | None = None
        self._owned_plugin_mcp_manager: Any | None = None
        # Plugin-contributed prompt commands and agent personas, populated in
        # ``Engine.create`` from plugin contributions. Commands map their
        # ``<plugin>:<stem>`` invocation (lowercased) → PluginCommand and are
        # expanded into the user message in ``_handle_send_message_inner``.
        # Agents map ``plugin:name`` (and bare ``name`` when unique) →
        # PluginAgent and are exposed to the ``agent`` tool (action="spawn")
        # via ``tool_context.metadata['plugin_agents']``.
        self.plugin_commands: dict[str, Any] = {}
        self.plugin_agents: dict[str, Any] = {}
        # Plugin ``rules`` — always-on system-level directives (CodeBuddy
        # convention). Their bodies are injected into the system prompt every
        # turn (declarative text, no execution).
        self.plugin_rules: list[Any] = []
        # Names of skills contributed by plugins (for UI surfacing / labeling).
        self.plugin_skill_names: set[str] = set()
        # Loaded-plugin summary + names for the startup banner and sidebar.
        self.plugin_summary: dict[str, int] = {}
        self.plugin_names: list[str] = []
        # Plugin contribution index (from lockfile) - name+description catalog
        # for prompt rendering without disk-scanning .md files. Populated in
        # ``Engine.create``; keys are plugin names, values are the index dict.
        self.plugin_index: dict[str, dict[str, Any]] = {}
        # Discovered LoadedPlugins, retained for on-demand heavy assembly
        # (commands/agents/rules). Skills are eager-merged into the registry;
        # these are kept so ``ensure_plugin_activated`` can find a plugin by
        # name without re-discovering.
        self._loaded_plugins: list[Any] = []
        # Lowercased plugin names present at Engine.create. Used to tip the
        # user when a mid-session install is mounted before hooks/MCP reload.
        self._session_plugin_names: set[str] = set()
        # Names of plugins already heavy-assembled (commands/agents/rules
        # loaded from disk). Idempotent guard for ``ensure_plugin_activated``.
        self._activated_plugins: set[str] = set()
        # Per-tool snapshots for /undo.
        # Maps tool_call_id → list[(absolute_path, original_bytes_or_None)].
        # None means file did not exist before the tool ran.
        self.tool_snapshots: dict[str, list[tuple[Path, bytes | None]]] = {}
        self._max_tool_snapshots = 5
        self._max_snapshot_file_size = 1_048_576  # 1 MB
        # Sampling / reasoning defaults — populated from Config in
        # ``Engine.create``. Without these, ``_run_conversation`` would
        # build a ``MessageRequest`` missing reasoning_effort/temperature
        # and DeepSeek-R1 / V4 thinking would never activate.
        self.default_reasoning_effort = default_reasoning_effort
        self.default_temperature = default_temperature
        self.default_top_p = default_top_p
        self.default_extra_body: dict[str, Any] = dict(default_extra_body or {})
        self._user_turn_index: int = 0
        from deepseek_tui.integrations.hooks import HookExecutor

        self.hook_executor: HookExecutor = (
            hook_executor if isinstance(hook_executor, HookExecutor) else HookExecutor.disabled()
        )
        self.tool_context.metadata["hook_executor"] = self.hook_executor
        from deepseek_tui.goal.service import GoalService
        from deepseek_tui.goal.types import GOAL_SERVICE_KEY

        self.goal_service = GoalService(on_update=self._emit_goal_updated)
        self.tool_context.metadata[GOAL_SERVICE_KEY] = self.goal_service
        # Expose the merged skill registry (workspace + plugin skills) so the
        # ``load_skill`` tool can resolve plugin skills by name. Without this,
        # load_skill re-discovers via discover_in_workspace which does not
        # merge plugin contributions, so plugin skills would be unreachable
        # by name even though they are listed in the system prompt.
        if skill_registry is not None:
            self.tool_context.metadata["skill_registry"] = skill_registry
        # Cycle manager — instantiated but disabled by default. The full
        # archive-and-replan logic lives in cycle.py; ``Engine`` keeps surface
        # integration minimal: ``_maybe_advance_cycle`` runs at the start of
        # each conversation and only fires when the user opts in via
        # ``Config.cycle_enabled``.
        self.cycle_config = CycleConfig(enabled=False)
        self._cycle_session_id: str = ""
        self._cycle_n: int = 0
        self._cycle_started_at: int = 0
        # Working-set tracker — observes user messages and tool calls to
        # surface relevant file paths for compaction pinning + system-prompt
        # injection. One per
        # Engine instance: workspace lives on tool_context.working_directory.
        self.working_set = WorkingSet(workspace=self.tool_context.working_directory)
        from deepseek_tui.engine.tool_dedup import ToolCallDeduplicator

        # Turn-local same-args anti-loop (reset at each _run_conversation).
        self._tool_dedup = ToolCallDeduplicator()
        self._mcp_tools_cache: list[dict[str, Any]] | None = None
        self.tool_profile: str | None = None
        # Issue #756: parent turn resumes when direct children complete.
        self._subagent_completions: asyncio.Queue[SubAgentCompletion] = (
            asyncio.Queue(maxsize=64)
        )
        self._consumed_subagent_completions: set[str] = set()
        self._process_completions: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=64
        )
        self._consumed_process_completions: set[str] = set()
        self.tool_context.on_shell_process_done = (
            self._enqueue_shell_process_completion
        )
        self._activity_coordinator = SessionActivityCoordinator(
            self, self.handle.try_emit
        )

    def _emit_goal_updated(self, snapshot: Any, change: Any) -> None:
        queue = tuple(item.to_dict() for item in self.goal_service.queue_items())
        self.handle.try_emit(
            GoalUpdatedEvent(
                snapshot=None if snapshot is None else snapshot.to_dict(),
                change=getattr(getattr(change, "kind", None), "value", "") or "lifecycle",
                status=getattr(getattr(change, "status", None), "value", None),
                reason=getattr(change, "reason", None) or "",
                queue=queue,
            )
        )

    async def launch_goal_continuation(self) -> bool:
        """Host-specific: TUI send_op, Workbench flags start_turn."""
        from deepseek_tui.goal.types import GOAL_CONTINUATION_KIND

        decision = self.goal_service.peek_continuation(mode=self.mode)
        if not decision.should_continue:
            return False
        if self.tool_context.metadata.get("runtime_thread_id"):
            self.tool_context.metadata["goal_continue_pending"] = True
            return True
        await self.handle.send_op(
            SendMessageOp(
                content=decision.prompt,
                hidden=True,
                internal_kind=GOAL_CONTINUATION_KIND,
            )
        )
        return True

    async def launch_promoted_goal(self, objective: str, item_id: str) -> bool:
        if self.tool_context.metadata.get("runtime_thread_id"):
            self.tool_context.metadata["goal_promote_pending"] = {
                "objective": objective,
                "item_id": item_id,
            }
            return False
        await self.handle.send_op(SendMessageOp(content=objective))
        return True

    async def _enforce_goal_wall_clock_deadline(
        self,
        goal_id: str,
        remaining_ms: int,
    ) -> None:
        from deepseek_tui.goal.types import GoalActor

        await asyncio.sleep(max(0, remaining_ms) / 1000)
        snapshot = self.goal_service.snapshot()
        if (
            snapshot is None
            or snapshot.goal_id != goal_id
            or snapshot.status.value != "active"
        ):
            return
        reason = (
            "Blocked after goal budget reached: "
            f"wall-clock budget {snapshot.budget.wall_clock_budget_ms}ms"
        )
        self.goal_service.mark_blocked(reason, actor=GoalActor.RUNTIME)
        await self.handle.cancel(reason="goal_wall_clock_budget_reached")

    async def _finish_goal_turn(
        self,
        *,
        cancelled: bool,
        failed: bool,
        error_message: str | None,
    ) -> None:
        total_output_tokens = int(
            self.turn_usage_ledger.totals().get("output_tokens") or 0
        )
        output_tokens = max(
            0,
            total_output_tokens - self._goal_accounted_output_tokens,
        )
        decision = self.goal_service.on_turn_ended(
            cancelled=cancelled,
            failed=failed,
            error_message=error_message,
            output_tokens=output_tokens,
            mode=self.mode,
        )
        if cancelled or failed:
            self.goal_service.discard_promoted()
            return
        promoted = self.goal_service.consume_promoted()
        if promoted is not None:
            try:
                self.goal_service.create(promoted.objective, mode=self.mode)
                launched = await self.launch_promoted_goal(
                    promoted.objective,
                    promoted.item_id,
                )
            except Exception:  # noqa: BLE001 — keep the item queued for retry
                logger.exception("goal_promote_failed")
                current = self.goal_service.snapshot()
                if current is not None and current.objective == promoted.objective:
                    from deepseek_tui.goal.types import GoalActor

                    self.goal_service.cancel(actor=GoalActor.RUNTIME)
            else:
                if launched:
                    self.goal_service.acknowledge_promoted(promoted.item_id)
                return
        if decision.should_continue:
            await self.launch_goal_continuation()

    def sync_session(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
    ) -> None:
        """Replace in-memory chat history."""
        self.session_messages.clear()
        self.session_messages.extend(messages)
        if model:
            self.default_model = model

    def invalidate_mcp_tools_cache(self) -> None:
        """Drop cached MCP tool descriptors so the next turn re-discovers."""
        self._mcp_tools_cache = None

    @property
    def mcp_manager(self):
        """Access the McpManager from the tool runtime (if configured)."""
        if self._session_mcp_manager is not None:
            return self._session_mcp_manager
        if self.tool_runtime is not None:
            return self.tool_runtime.mcp_manager
        from deepseek_tui.tools.mcp import MCP_MANAGER_KEY
        return self.tool_context.metadata.get(MCP_MANAGER_KEY)

    def _server_tool_names(self, server: str) -> set[str]:
        """某 MCP server 在 catalog 里的最终限定工具名集合。

        取 ``grouped_discovered_tools()[server]`` 的 ``model_name``，避免
        ``mcp_<server>_<tool>`` 下划线歧义。无 manager / 未发现 → 空集。
        """
        mcp = self.mcp_manager
        if mcp is None:
            return set()
        grouped = mcp.grouped_discovered_tools()
        return {
            entry["model_name"]
            for entry in grouped.get(server, [])
            if entry.get("model_name")
        }

    def _mcp_focus_whitelist(
        self, server: str
    ) -> tuple[frozenset[str], frozenset[str]]:
        """聚焦某个 MCP 连接器时的工具白名单 + 放行 server 集合。

        返回 ``(tool_names, server_names)``。tool_names = ``FOCUS_MCP_BASE``
        ∪ 该 server 已发现工具名；server_names 含该 server 名，让 lazy 未
        discovery 的工具也能按 server 级放行（修白名单竞态：lazy server 在
        首次工具调用前 tool 名未知，按 server 名前缀匹配兜底放行）。

        连接器聚焦不仅查询连接器，还要能对工作区动手（kernel 含写/exec/web）。
        """
        tool_names = frozenset(
            self._server_tool_names(server) | FOCUS_MCP_BASE
        )
        return tool_names, frozenset({server})

    def set_active_plugin(self, name: str | None) -> str:
        """进入 / 退出会话级场景模式。``name=None`` 或 ``"off"`` → 退出。

        按名在已发现插件里大小写不敏感查找并存入 ``self._active_plugin``；
        返回一条给用户看的结果说明。未找到时保持原状并回错。
        """
        if name is None or name.lower() == "off":
            self._active_plugin = None
            self._scenario_agent = None
            if self.hook_executor is not None:
                self.hook_executor.scenario_plugin = None
            return "已退出场景，恢复全量工具与技能。"
        match = None
        if self.plugin_session is not None:
            match = self.plugin_session.plugin(name)
        if match is None and self._loaded_plugins:
            match = next(
                (
                    p
                    for p in self._loaded_plugins
                    if p.manifest.name.lower() == name.lower()
                ),
                None,
            )
        if match is None:
            return f"未找到插件：{name}（用 plugin list 查看已安装）。"
        # Refresh enable/trust from the lockfile so an in-session trust toggle
        # is visible on remount, without reloading package formats or bodies.
        if self.plugin_session is not None:
            self.plugin_session.invalidate_light(match.name)
            refreshed = self.plugin_session.plugin(match.name)
            if refreshed is not None:
                match = refreshed
        self._active_plugin = match
        if self.hook_executor is not None:
            self.hook_executor.scenario_plugin = match.manifest.name
        if self.tool_context is not None:
            trust_map = self.tool_context.metadata.setdefault("plugin_trust", {})
            if isinstance(trust_map, dict):
                trust_map[match.manifest.name.lower()] = bool(
                    getattr(match, "trusted", False)
                )
        m = match.manifest
        note = f"已进入场景 {m.name}，本会话仅用其工具 + 基础工具。"
        # trusted 才收 MCP；未信任时提示。
        if m.mcp_servers and not getattr(match, "trusted", False):
            note += " 注意：该插件的 MCP 未激活，需先信任该插件。"
        elif m.mcp_servers and getattr(match, "trusted", False):
            # MCP servers are injected only at Engine.create. In-session trust
            # cannot register a new server into the live manager.
            owned = getattr(self, "_owned_plugin_mcp_manager", None)
            manager_names = {
                n.lower() for n in (owned.server_names if owned is not None else [])
            }
            light = None
            if self.plugin_session is not None:
                try:
                    light = self.plugin_session.light_contributions(m.name)
                except Exception:  # noqa: BLE001
                    light = None
            declared = (
                [s.name for s in light.mcp_servers] if light is not None else []
            )
            if not declared or any(
                name.lower() not in manager_names for name in declared
            ):
                note += (
                    " 注意：该插件的 MCP 未在本会话启动时注册，"
                    "需新开会话后才会生效。"
                )
        if m.name.lower() not in self._session_plugin_names:
            note += (
                " 注意：本会话启动后新发现的插件，其 hooks/MCP "
                "需新开会话才会生效。"
            )
        # Ensure heavy components (commands/agents/rules) are loaded for
        # this plugin so prompt rendering and command dispatch work.
        self.ensure_plugin_activated(m.name, plugin=match)
        # settings.json ``defaultAgent``: mounting the plugin makes that
        # agent the main-thread persona (its body joins the system prompt).
        self._scenario_agent = None
        default_agent = (getattr(m, "default_agent", "") or "").strip()
        if default_agent:
            agent = self.plugin_agents.get(
                f"{m.name}:{default_agent}".lower()
            ) or self.plugin_agents.get(default_agent.lower())
            if agent is not None:
                self._scenario_agent = agent
                note += f" 已激活主线程 agent：{agent.name}。"
            else:
                note += f" 注意：声明的默认 agent「{default_agent}」未找到。"
        return note

    def ensure_plugin_activated(
        self, name: str, *, plugin: object | None = None
    ) -> bool:
        """Lazily heavy-assemble a single plugin's commands/agents/rules.

        Loads declarative text components from disk for the named plugin and
        merges them into the engine's active state (``plugin_commands``,
        ``plugin_agents``, ``plugin_rules``). Idempotent: a second call for an
        already-activated plugin is a no-op. Returns ``True`` if the plugin
        was found and is now (or already was) activated.

        Skills are NOT handled here -- they are eager-merged into the
        ``SkillRegistry`` at ``Engine.create`` because ``load_skill`` and the
        ``## Skills`` prompt section need them without an activation step.

        After activation the plugin's entry is removed from ``plugin_index``
        so render methods don't double-list its commands/agents/rules (real
        objects in the live dicts + stale proxies in the index). Name
        matching is case-insensitive to stay consistent with
        ``set_active_plugin`` and ``_expand_plugin_command``.
        """
        name_lower = name.lower()
        if name_lower in self._activated_plugins:
            return True
        session = self.plugin_session
        if session is None:
            return False

        try:
            activation = session.activate(name)
        except Exception:  # noqa: BLE001 - a malformed plugin must not crash
            logger.warning(
                "plugin heavy assembly failed for %s", name, exc_info=True
            )
            return False
        if activation is None:
            return False
        for c in activation.commands:
            self.plugin_commands[c.qualified.lower()] = c
        for a in activation.agents:
            _register_plugin_agent(self.plugin_agents, a)
        if self.plugin_agents:
            self.tool_context.metadata["plugin_agents"] = self.plugin_agents
        for r in activation.rules:
            if r not in self.plugin_rules:
                self.plugin_rules.append(r)
        self._activated_plugins.add(name_lower)
        # Clear commands/agents/rules from the index so render methods don't
        # double-list them (real objects are now in the live dicts). Skills
        # are preserved -- ``_active_plugin_skills`` reads them from the
        # index to filter the SkillRegistry when a plugin is mounted.
        loaded = session.plugin(name)
        entry = self.plugin_index.get(loaded.name) if loaded is not None else None
        if isinstance(entry, dict):
            entry["commands"] = []
            entry["agents"] = []
            entry["rules"] = []
        logger.info("plugin_activated name=%s", loaded.name)
        return True

    def _active_plugin_skills(self) -> list[object]:
        """当前挂载插件贡献的 skill 集（用于收窄 system prompt 注入）。

        Skills are already in the registry (eager-loaded at create time);
        filter by the mounted plugin's index instead of re-scanning disk.
        """
        if self._active_plugin is None:
            return []
        if self.skill_registry is None:
            return []
        plugin_name = self._active_plugin.name
        idx = self.plugin_index.get(plugin_name, {})
        skill_names = {
            s["name"]
            for s in idx.get("skills", [])
            if isinstance(s, dict) and s.get("name")
        }
        if not skill_names:
            # No index -- fall back to registry skills whose path is under
            # the plugin directory.
            try:
                plugin_root = self._active_plugin.path.resolve()
            except (OSError, ValueError):
                return []
            return [
                s
                for s in self.skill_registry.skills
                if _path_under(s.path, plugin_root)
            ]
        # Registry names are qualified (``plugin:skill``); older lockfile
        # indexes may store bare names — match either form.
        return [
            s
            for s in self.skill_registry.skills
            if s.name in skill_names
            or s.name.split(":", 1)[-1] in skill_names
        ]

    def _plugin_catalog_entries(self) -> list[Any]:
        """Build thin-catalog rows from loaded plugins + index/live counts."""
        from types import SimpleNamespace

        if not self._loaded_plugins:
            return []
        entries: list[Any] = []
        for plugin in self._loaded_plugins:
            name = plugin.name
            idx = self.plugin_index.get(name) or {}
            n_skills = len(idx.get("skills") or [])
            n_commands = len(idx.get("commands") or []) + sum(
                1
                for c in self.plugin_commands.values()
                if getattr(c, "plugin", None) == name
            )
            n_agents = len(idx.get("agents") or []) + sum(
                1
                for a in _unique_plugin_agents(self.plugin_agents)
                if getattr(a, "plugin", None) == name
            )
            n_rules = len(idx.get("rules") or []) + sum(
                1
                for r in self.plugin_rules
                if getattr(r, "plugin", None) == name
            )
            n_mcp = len(idx.get("mcp_servers") or [])
            if not n_mcp and plugin.manifest.mcp_servers:
                n_mcp = 1
            n_hooks = len(idx.get("hooks_events") or [])
            if not n_hooks and plugin.manifest.hooks:
                n_hooks = len(plugin.manifest.hooks)
            entries.append(
                SimpleNamespace(
                    name=name,
                    description=plugin.manifest.description or "",
                    skills=n_skills,
                    commands=n_commands,
                    agents=n_agents,
                    rules=n_rules,
                    mcp=n_mcp,
                    hooks=n_hooks,
                )
            )
        return entries

    def _active_plugin_whitelist(
        self,
    ) -> tuple[frozenset[str], frozenset[str]] | None:
        """当前挂载插件的每轮工具白名单 + 放行 server 集合。

        返回 ``(tool_names, server_names)`` 或 ``None``（未挂载）。

        tool_names = ``FOCUS_PLUGIN_BASE`` ∪ skill ``allowed-tools`` ∪
        trusted plugin MCP tool names. Authors rarely declare allowed-tools,
        so the plugin base must already be runnable.

        server_names = trusted MCP servers for lazy discovery-independent
        prefix allow. Trust gates **plugin processes** (hooks / MCP), not
        built-in exec/write/shell.
        """
        plugin = self._active_plugin
        if plugin is None:
            return None

        allowed: set[str] = set(FOCUS_PLUGIN_BASE)
        server_names: set[str] = set()
        # Skill allowed-tools always expand the mount surface (extras like
        # task_*). Trust is not required for built-in declares.
        for skill in self._active_plugin_skills():
            declared = getattr(skill, "allowed_tools", None)
            if declared:
                allowed |= set(declared)
        contribs = None
        if self.plugin_session is not None:
            try:
                contribs = self.plugin_session.light_contributions(plugin.name)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "plugin session light contributions failed", exc_info=True
                )
        if contribs is not None and plugin.trusted:
            for server in contribs.mcp_servers:
                allowed |= self._server_tool_names(server.name)
                server_names.add(server.name)
        return frozenset(allowed), frozenset(server_names)

    def _render_plugin_context(self) -> str | None:
        """Render the ``## Active Plugin`` system-prompt block.

        Tells the model the plugin directory + that reads under it are
        permitted, paired with the silent ``extra_read_roots`` grant applied
        each turn. Without this block the model only sees base.md's
        path-escape rule and would never read plugin files. Returns ``None``
        when no plugin is mounted.
        """
        plugin = self._active_plugin
        if plugin is None:
            return None
        from deepseek_tui.engine.prompts import render_plugin_context

        has_mcp = bool(plugin.manifest.mcp_servers)
        block = render_plugin_context(
            name=plugin.name,
            version=plugin.manifest.version,
            path=str(plugin.path.expanduser().resolve()),
            permissions=plugin.manifest.permissions,
            trusted=plugin.trusted,
            mcp_active=has_mcp and plugin.trusted,
            has_mcp=has_mcp,
        )
        agent = self._scenario_agent
        body = (getattr(agent, "body", "") or "").strip() if agent is not None else ""
        if body:
            block += (
                f"\n\n## Active Plugin Agent: {agent.name}\n"
                "While this plugin is mounted you act as the agent below. "
                "Its instructions extend (and on conflict override) your "
                "general behavior for this scenario.\n\n"
                f"{body}"
            )
        return block

    def _render_plugin_components_context(self) -> str | None:
        """Render plugin contribution surface for the system prompt.

        Small installs keep a per-command/agent listing. Larger ones switch
        to the thin ``## Installed Plugins`` catalog so marketplace-scale
        installs don't dilute the session-stable prefix. Suppressed while a
        plugin is mounted (scenario already narrows the surface).
        """
        if self._active_plugin is not None:
            return None
        from deepseek_tui.engine.prompts import (
            PLUGIN_DETAILED_LIST_LIMIT,
            render_installed_plugins_catalog,
            render_plugin_components_context,
        )

        commands: list[Any] = list(self.plugin_commands.values())
        agents: list[Any] = _unique_plugin_agents(self.plugin_agents)
        if self.plugin_index:
            commands = commands + _index_command_proxies(self.plugin_index)
            agents = agents + _index_agent_proxies(self.plugin_index)
        total = len(commands) + len(agents)
        if total == 0 and not self._loaded_plugins:
            return None
        if total <= PLUGIN_DETAILED_LIST_LIMIT and total > 0:
            block = render_plugin_components_context(commands, agents)
            return block or None
        catalog = self._plugin_catalog_entries()
        if not catalog:
            return None
        block = render_installed_plugins_catalog(catalog)
        return block or None

    def _render_plugin_rules_context(self) -> str | None:
        """Render plugin ``rules`` as a system-prompt block.

        CodeBuddy plugins carry their core behavior in ``rules`` marked
        ``alwaysApply: true``. Mounted (``@plugin:name``): the mounted
        plugin's rule bodies are injected verbatim — that IS the plugin's
        behavior the user opted into. Plugins without ``rules/`` inject
        nothing (README is human docs only). Unmounted: rules collapse to
        one summary line each with a mount hint (full bodies from every
        installed plugin would bloat and dilute the prompt).
        """
        active_plugin = self._active_plugin
        if (
            not self.plugin_rules
            and not self.plugin_index
            and active_plugin is None
        ):
            return None
        from deepseek_tui.engine.prompts import render_plugin_rules_context

        active = active_plugin.name if active_plugin is not None else None
        if active is not None:
            rules = self.plugin_rules
        else:
            rules = list(self.plugin_rules)
            if self.plugin_index:
                rules = rules + _index_rule_proxies(self.plugin_index)
        if not rules:
            return None
        block = render_plugin_rules_context(rules, active_plugin=active)
        return block or None

    async def _get_tools_with_mcp(self) -> list[dict[str, Any]]:
        """Build the full tool list: native registry + discovered MCP tools."""
        from deepseek_tui.server.metrics import get_turn_latency, now_ms
        from deepseek_tui.engine.prompts import (
            TOOL_PROFILE_FULL,
            filter_tools_for_profile,
        )

        turn_id = self.tool_context.metadata.get("turn_latency_turn_id")
        trace = get_turn_latency(str(turn_id)) if turn_id else None
        build_start = now_ms() if trace is not None else None

        native_tools = self.tool_registry.to_api_tools()
        mcp = self.mcp_manager
        profile = self.tool_profile or TOOL_PROFILE_FULL
        mode = (self.mode or "agent").strip() or "agent"
        if mode == "plan":
            # Shared agent registries still expose write tools; filter the
            # model-visible surface to the plan allowlist.
            native_tools = [
                t
                for t in native_tools
                if (t.get("function") or t).get("name") in PLAN_MODE_TOOL_ALLOWLIST
            ]
        if mcp is None:
            result = filter_tools_for_profile(list(native_tools), profile)
        else:
            mcp_tools = self._mcp_tools_cache
            if mcp_tools is None:
                mcp_tools = mcp.cached_tools()
            # Always kick discover: cold start has no tools; stale cache
            # (load_policy change) omits newly progressive servers.
            mcp.schedule_background_discover()
            if mcp_tools is None:
                # Never block a user turn on cold MCP subprocess startup.
                logger.info("mcp_discover_deferred native_tools=%d", len(native_tools))
                result = filter_tools_for_profile(list(native_tools), profile)
            elif not mcp_tools:
                result = filter_tools_for_profile(list(native_tools), profile)
            else:
                self._mcp_tools_cache = list(mcp_tools)
                combined = build_model_tool_catalog(
                    list(native_tools), list(mcp_tools), self.mode
                )
                result = filter_tools_for_profile(combined, profile)

        # on_focus (@connector) tools are kept out of progressive cache —
        # merge them in only while a focus whitelist is active.
        if (
            self._focus_allowed_servers
            and mcp is not None
            and hasattr(mcp, "focus_api_tools")
        ):
            focus_extra: list[dict[str, Any]] = []
            for server in self._focus_allowed_servers:
                focus_extra.extend(mcp.focus_api_tools(server))
            if focus_extra:
                combined = build_model_tool_catalog(
                    list(result), list(focus_extra), self.mode
                )
                result = filter_tools_for_profile(combined, profile)

        # 聚焦模式：收窄到最小工具白名单。MCP 工具额外按 server 级放行：
        # lazy server 未 discovery 时工具名未知，通过
        # _match_configured_server 前缀匹配兜底。
        if self._focus_tool_whitelist is not None:
            whitelist = self._focus_tool_whitelist
            allowed_servers = self._focus_allowed_servers
            mcp_mgr = self.mcp_manager

            def _passes_focus(tool: dict[str, Any]) -> bool:
                fn = tool.get("function", tool) or {}
                name = fn.get("name")
                if not isinstance(name, str):
                    return True
                if name in whitelist:
                    return True
                # Lazy MCP server: tool name unknown until discovery, so
                # match by configured server prefix (discovery-independent).
                if allowed_servers and mcp_mgr is not None:
                    server = mcp_mgr._match_configured_server(name)
                    if server is not None and server in allowed_servers:
                        return True
                return False

            result = [t for t in result if _passes_focus(t)]

        if mode == "plan":
            result = [
                t
                for t in result
                if (t.get("function") or t).get("name") in PLAN_MODE_TOOL_ALLOWLIST
            ]

        from deepseek_tui.goal.types import GOAL_CONTROL_TOOL_NAMES

        if self.goal_service.snapshot() is None:
            result = [
                t
                for t in result
                if (t.get("function") or t).get("name") not in GOAL_CONTROL_TOOL_NAMES
            ]

        if trace is not None and build_start is not None:
            trace.note_catalog_build(build_start, now_ms() - build_start, len(result))
        return result

    @classmethod
    async def create(
        cls,
        handle: EngineHandle,
        client: LLMClient,
        *,
        config: object | None = None,
        working_directory: Path | None = None,
        mode: str = "agent",
        default_model: str = "deepseek-chat",
        exec_policy: ExecPolicyEngine | None = None,
        approval_handler: ApprovalHandler | None = None,
        max_tool_round_trips: int = 200,
        task_data_dir: Path | None = None,
        tool_runtime: object | None = None,
        start_mcp: bool | None = None,
        mcp_manager: object | None = None,
    ) -> Engine:
        """Construct an Engine with a freshly-wired :class:`ToolRuntime`.
        归一 config → 起/复用工具运行时 → 发现 skills → 修正工作区 context(踩坑补丁) → 造实例 → 包计费 → 建 TurnLoop → 装容量/实验特性 → 同步沙箱 → 接线子代理 → 返回。
        """
        from deepseek_tui.config.models import Config
        from deepseek_tui.integrations.skills import discover_in_workspace
        from deepseek_tui.tools.runtime import ToolRuntime, create_tool_runtime
        # 装配 HookDispatcher + HookExecutor
        cfg = config if isinstance(config, Config) else Config()
        from deepseek_tui.integrations.hooks import build_hook_dispatcher, build_lifecycle_hook_executor

        if handle.hooks is None:
            handle.attach_hooks(build_hook_dispatcher(cfg))
        ws = working_directory or Path.cwd()
        # Open one frozen plugin session and fan its startup contributions out
        # to the existing host subsystems. Engine does not discover package
        # formats or know how the plugin host assembled these contributions.
        plugin_session = None
        plugin_contribs = None
        plugin_skill_contribs = None
        loaded_plugins: list[Any] = []
        if cfg.features.plugins:
            from deepseek_tui.plugins import PluginHost

            try:
                plugin_session = PluginHost().open_session(workspace=ws)
                loaded_plugins = list(plugin_session.loaded_plugins)
                plugin_contribs = plugin_session.startup
                plugin_skill_contribs = plugin_session.startup
            except Exception:  # noqa: BLE001 — a malformed plugin must not
                # crash engine construction; degrade to no plugin contributions.
                logger.warning("plugin discovery failed", exc_info=True)
            if plugin_contribs is not None:
                for warning in plugin_contribs.warnings:
                    logger.warning("plugin: %s", warning)
            if plugin_skill_contribs is not None:
                for warning in plugin_skill_contribs.warnings:
                    logger.warning("plugin: %s", warning)
        hooks_cfg = cfg
        if plugin_contribs is not None and plugin_contribs.hook_entries:
            hooks_cfg = cfg.model_copy(
                update={
                    "hooks": cfg.hooks.model_copy(
                        update={
                            "hooks": list(cfg.hooks.hooks)
                            + plugin_contribs.hook_entries
                        }
                    )
                }
            )
        hook_executor = build_lifecycle_hook_executor(hooks_cfg, ws)
        if isinstance(tool_runtime, ToolRuntime):
            runtime = tool_runtime
        else:
            mcp_flag = cfg.features.mcp if start_mcp is None else start_mcp
            # Engine的「工具运行时装配工厂」—— 把Engine跑工具需要的所有依赖(managers + registry + context + policies)
            # 按配置组装成一个ToolRuntime对象交出去。 Engine自己不管这些manager怎么建、executor怎么注入
            runtime = await create_tool_runtime(
                config=cfg,
                working_directory=working_directory,
                mode=mode,
                task_data_dir=task_data_dir,
                start_mcp=mcp_flag,
                mcp_manager=mcp_manager,  # type: ignore[arg-type]
                extra_mcp_servers=(
                    plugin_contribs.mcp_servers if plugin_contribs else None
                ),
            )
        # Make [providers.X] context_window overrides visible to
        # context_window_for_model() even when Config was built directly
        # (server / tests) instead of through ConfigLoader.load.
        from deepseek_tui.config.providers import register_provider_context_windows

        register_provider_context_windows(cfg)
        # Discover skills for system prompt injection
        skill_reg = discover_in_workspace(workspace=working_directory)
        if plugin_skill_contribs is not None and plugin_skill_contribs.skills:
            from deepseek_tui.plugins.host import merge_session_skills

            merge_session_skills(skill_reg, plugin_skill_contribs)
        # Pull sampling / reasoning defaults out of Config so the per-turn
        # MessageRequest carries them all the way to DeepSeekClient.
        provider_cfg = cfg.effective_provider_config()
        # When reusing a shared runtime, create a per-engine ToolContext with
        # the correct working_directory so system prompts reflect the thread's
        # workspace rather than the process cwd. We branch off the runtime's
        # context instead of constructing a bare one, otherwise the per-engine
        # context loses task_manager/subagent_manager/network_policy/policy and
        # registered-but-runtime-unwired tools (e.g. task_create) become
        # guaranteed failures. metadata is shallow-copied so per-engine writes
        # don't mutate the shared one.
        #
        # Sub-agents are engine-scoped: the shared runtime's single
        # SubAgentManager + Mailbox must NOT be reused across engines. The
        # Mailbox is a single-consumer queue, so with N engines each running
        # a SessionActivityCoordinator, one thread's coordinator steals
        # another thread's progress envelopes (cards never render). Sharing
        # the manager also lets each new engine's attach_loop_runtime /
        # attach_parent_cancel overwrite the previous engine's wiring. Give
        # every engine its own manager + mailbox instead.
        import dataclasses as _dc

        per_engine_context: ToolContext | None = None
        per_engine_subagent_manager = None
        session_mcp_manager = None
        owned_plugin_mcp_manager = None
        if isinstance(tool_runtime, ToolRuntime):
            from deepseek_tui.tools.runtime import build_subagent_manager

            per_engine_subagent_manager, _ = build_subagent_manager(cfg, ws)
            per_engine_context = _dc.replace(
                runtime.context,
                working_directory=ws,
                subagent_manager=per_engine_subagent_manager,
                metadata=dict(runtime.context.metadata),
                # Same reason as metadata: replace() would otherwise alias the
                # runtime's dict into every engine built from it.
                file_reads={},
            )
            if (
                cfg.features.mcp
                and plugin_contribs is not None
                and plugin_contribs.mcp_servers
            ):
                from deepseek_tui.mcp.manager import McpManager
                from deepseek_tui.plugins.runtime import CompositeMcpManager
                from deepseek_tui.tools.mcp import MCP_MANAGER_KEY

                base_mcp = runtime.mcp_manager
                base_names = set(base_mcp.server_names if base_mcp else ())
                plugin_servers = [
                    server
                    for server in plugin_contribs.mcp_servers
                    if server.name not in base_names
                ]
                if plugin_servers:
                    owned_plugin_mcp_manager = McpManager(plugin_servers)
                    session_mcp_manager = CompositeMcpManager(
                        base_mcp,
                        owned_plugin_mcp_manager,
                    )
                    per_engine_context.metadata[MCP_MANAGER_KEY] = (
                        session_mcp_manager
                    )
        engine = cls(
            handle=handle,
            client=client,
            default_model=default_model,
            exec_policy=exec_policy,
            approval_handler=approval_handler,
            max_tool_round_trips=max_tool_round_trips,
            tool_runtime=runtime,
            tool_context=per_engine_context,
            skill_registry=skill_reg,
            default_reasoning_effort=cfg.reasoning_effort,
            default_temperature=provider_cfg.temperature,
            default_top_p=None,
            default_extra_body=dict(provider_cfg.extra_body or {}),
            hook_executor=hook_executor,
        )
        locale = getattr(getattr(cfg, "ui", None), "locale", None)
        engine.reply_locale = locale if locale in ("zh", "en") else "zh"
        engine.plugin_session = plugin_session
        engine._session_mcp_manager = session_mcp_manager
        engine._owned_plugin_mcp_manager = owned_plugin_mcp_manager
        from deepseek_tui.client.base import MeteredLLMClient

        if isinstance(client, MeteredLLMClient):
            engine.turn_usage_ledger = client._ledger
        else:
            engine.client = MeteredLLMClient(client, engine.turn_usage_ledger)
        engine.turn_loop = TurnLoop(engine.client, compact_fn=engine._emergency_compact)
        if isinstance(tool_runtime, ToolRuntime):
            engine._owns_tool_runtime = False
        # Register plugin index + skill names for prompt rendering.
        # Commands/agents/rules are deferred -- ``ensure_plugin_activated``
        # loads them on-demand (mount, slash-command dispatch, agent spawn).
        # The lockfile contribution index drives the prompt catalog without
        # disk-scanning .md files, so a workspace with many plugins pays
        # zero heavy-assembly cost at startup.
        #
        # Plugins whose lockfile entry predates the index (or was written by
        # an older install) have ``contribution_index is None``. For those we
        # fall back to eager heavy assembly so backward compatibility holds --
        # the optimization is opt-in per plugin, not all-or-nothing.
        if loaded_plugins:
            engine._loaded_plugins = loaded_plugins
            engine._session_plugin_names = {
                p.name.lower() for p in loaded_plugins
            }
            engine.plugin_index = {
                p.name: p.contribution_index
                for p in loaded_plugins
                if p.contribution_index
            }
            engine.plugin_skill_names = {
                s.name
                for s in (plugin_skill_contribs.skills if plugin_skill_contribs else [])
            }
            # Backward-compatible eager assembly for plugins without an index.
            unindexed = [p for p in loaded_plugins if p.contribution_index is None]
            if unindexed:
                for plugin in unindexed:
                    engine.ensure_plugin_activated(plugin.name, plugin=plugin)
            # Summary counts: skills from eager collection, commands/agents/rules
            # from the index + eager fallback, hooks/mcp from light contributions.
            idx = engine.plugin_index
            engine.plugin_summary = {
                "plugins": len(loaded_plugins),
                "skills": len(engine.plugin_skill_names),
                "commands": sum(len(i.get("commands", [])) for i in idx.values())
                + len(engine.plugin_commands),
                "agents": sum(len(i.get("agents", [])) for i in idx.values())
                + len(_unique_plugin_agents(engine.plugin_agents)),
                "rules": sum(len(i.get("rules", [])) for i in idx.values())
                + len(engine.plugin_rules),
                "hooks": len(plugin_contribs.hook_entries) if plugin_contribs else 0,
                "mcp": len(plugin_contribs.mcp_servers) if plugin_contribs else 0,
            }
            engine.plugin_names = [p.name for p in loaded_plugins]
            # Wire activation callback + agent-name index into tool context so
            # the ``agent`` tool (action="spawn") can lazily activate a plugin
            # when resolving a persona that hasn't been heavy-assembled yet.
            if engine.tool_context is not None:
                engine.tool_context.metadata["activate_plugin"] = (
                    engine.ensure_plugin_activated
                )
                engine.tool_context.metadata["plugin_agent_index"] = (
                    _agent_index_from_plugin_index(engine.plugin_index)
                )
                engine.tool_context.metadata["plugin_trust"] = {
                    p.name.lower(): bool(p.trusted) for p in loaded_plugins
                }
        engine.capacity_controller = CapacityController(
            config=CapacityControllerConfig.from_app_config(cfg.capacity)
        )
        # Cycle wiring — ratios from ContextConfig; absolute token
        # cutoffs are derived per request from the live model window.
        ctx_cfg = getattr(cfg, "context", None)
        engine.cycle_config = CycleConfig(
            enabled=bool(getattr(cfg, "cycle_enabled", False)),
            cycle_ratio=float(getattr(ctx_cfg, "cycle_ratio", 0.90) or 0.90),
        )
        engine.compaction_config.rewrite_ratio = float(
            getattr(ctx_cfg, "rewrite_ratio", 0.75) or 0.75
        )
        engine.compaction_config.l0_prune_ratio = float(
            getattr(ctx_cfg, "l0_prune_ratio", 0.50) or 0.50
        )
        engine._cycle_session_id = uuid.uuid4().hex
        engine._cycle_started_at = int(time.time())
        engine.mode = mode
        engine._app_config = cfg
        from deepseek_tui.policy.sandbox import sync_execution_sandbox_policy

        sync_execution_sandbox_policy(
            engine.tool_context,
            mode,
            engine.tool_context.working_directory,
        )
        # Wire the engine's own manager (per-engine when the runtime is
        # shared, the runtime's own otherwise) — never the shared one, so
        # cancel tokens / completion sinks / loop runtimes stay engine-local.
        engine._owns_subagent_manager = per_engine_subagent_manager is not None
        subagent_manager = engine.tool_context.subagent_manager
        if subagent_manager is not None:
            subagent_manager.attach_parent_cancel(handle.cancel_event)
            subagent_manager.attach_parent_completion_sink(
                engine._enqueue_subagent_completion
            )
            from deepseek_tui.tools.subagent import SubAgentRuntime

            auto_approve = await engine.approval_handler.auto_approve_enabled()
            loop_runtime = SubAgentRuntime(
                manager=subagent_manager,
                client=engine.client,
                model=default_model,
                config=cfg,
                workspace=ws.resolve(),  # noqa: ASYNC240
                allow_shell=getattr(cfg, "allow_shell", True),
                auto_approve=auto_approve,
                task_manager=runtime.task_manager,
                cancel_token=handle.cancel_event,
                mailbox=subagent_manager.mailbox,
                approval_handler=engine.approval_handler,
                emit_event=handle.emit,
                hook_executor=engine.hook_executor,
            )
            subagent_manager.attach_loop_runtime(loop_runtime)


        return engine

    async def shutdown_session(self) -> None:
        """Stop background coordinators and tool runtime (tests / teardown)."""
        await self._activity_coordinator.stop()
        if self._owns_subagent_manager:
            manager = self.tool_context.subagent_manager
            if manager is not None:
                if manager.mailbox is not None:
                    manager.mailbox.close()
                await manager.shutdown()
        if self._owned_plugin_mcp_manager is not None:
            await self._owned_plugin_mcp_manager.stop_all()
            self._owned_plugin_mcp_manager = None
            self._session_mcp_manager = None
        if self.plugin_session is not None:
            try:
                await self.plugin_session.close()
            except Exception:  # noqa: BLE001
                logger.warning("plugin session close failed", exc_info=True)
            self.plugin_session = None
        if self.tool_runtime is not None and self._owns_tool_runtime:
            await self.tool_runtime.shutdown()



    def _render_skills_context(self, only: object | None = None) -> str | None:
        """Render skills context for system prompt injection.

        ``only`` 为聚焦目标：可传单个 Skill（skill 聚焦）或一组 Skill 列表
        （插件挂载时其自带的多个 skill）。传入时只把这些 skill 列进
        ``## Skills`` 段（用临时 registry，不改 ``self.skill_registry``）；
        为 ``None`` 时渲染全量（默认）。空列表视同 ``None``。
        """
        if self.skill_registry is None:
            return None
        from deepseek_tui.integrations.skills import (
            SkillRegistry,
            render_available_skills_context,
        )

        registry = self.skill_registry
        if only is not None:
            skills = list(only) if isinstance(only, (list, tuple)) else [only]
            if not skills:
                return None
            registry = SkillRegistry(skills=skills)
        return render_available_skills_context(registry) or None

    def _accrue_child_token_cost_from_metadata(
        self, metadata: dict[str, Any] | None
    ) -> None:
        """Roll child-tool token usage into session cost."""
        if not metadata:
            return
        child_model = metadata.get("child_model")
        if not isinstance(child_model, str) or not child_model.strip():
            return
        input_tokens = int(metadata.get("child_input_tokens") or 0)
        output_tokens = int(metadata.get("child_output_tokens") or 0)
        if input_tokens == 0 and output_tokens == 0:
            return
        from deepseek_tui.protocol.responses import Usage

        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=int(
                metadata.get("child_prompt_cache_hit_tokens") or 0
            ),
            cache_creation_input_tokens=int(
                metadata.get("child_prompt_cache_miss_tokens") or 0
            ),
        )
        # Metadata-only child totals when the parent client
        # did not already meter the same subagent streams this turn.
        if not any(item.source in {"subagent", "tool"} for item in self.turn_usage_ledger.items):
            self.turn_usage_ledger.add(
                model=child_model,
                source="subagent",
                usage=usage,
            )

    def _take_handoff_reminder_message(self) -> Message | None:
        """Return a handoff reminder if the on-disk file is new/changed.

        Injected as a user-role ``<system-reminder>`` so the system prompt
        stays stable for DeepSeek prefix caching. Working-set paths stay out
        of system entirely (compaction bridge / cycle state only).
        """
        from deepseek_tui.engine import reminders
        from deepseek_tui.engine.prompts import handoff_path, load_handoff_reminder

        workspace = self.tool_context.working_directory
        path = handoff_path(workspace)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if (
            self._handoff_injected_mtime is not None
            and mtime <= self._handoff_injected_mtime
        ):
            return None
        body = load_handoff_reminder(workspace)
        if not body:
            return None
        self._handoff_injected_mtime = mtime
        return reminders.reminder_message(reminders.HANDOFF, body)

    def _take_git_snapshot_message(self) -> Message | None:
        """Return the one-shot session-start git snapshot, or None.

        Fires exactly once per engine lifetime (first real user turn).
        Like the handoff reminder, it rides in the message stream as a
        user-role ``<system-reminder>`` so the system prompt stays
        prefix-cacheable. The snapshot text itself says it will not
        update, so the model knows to re-query git for fresh state.
        """
        if self._git_snapshot_injected:
            return None
        self._git_snapshot_injected = True
        from deepseek_tui.engine import reminders
        from deepseek_tui.engine.prompts import collect_git_snapshot

        snapshot = collect_git_snapshot(self.tool_context.working_directory)
        if snapshot is None:
            return None
        return reminders.reminder_message(reminders.GIT_SNAPSHOT, snapshot)

    def context_breakdown(self, model: str | None = None) -> dict[str, int]:
        """Estimate token occupancy by category for the next request.

        Returns ``{bucket_name: tokens, ..., "total": int, "window": int}``.
        Buckets:

        - ``system_prompt`` — base system prompt body
        - ``tools`` — legacy combined JSON schema bucket
        - ``tool_definitions`` — built-in tool schemas sent to the model
        - ``mcp`` — discovered MCP tool schemas sent to the model
        - ``skills`` — available skills prompt section
        - ``rules`` — project instruction files (AGENTS / CLAUDE / instructions)
        - ``conversation`` — accumulated user/assistant/tool messages
        - ``free`` — derived as ``window - total``, clamped at 0

        ``window`` reads ``context_window_for_model``; ``model`` defaults
        to ``self.default_model``.

        Token counts use the same conservative estimators as
        :func:`engine.context.estimate_context_breakdown`.
        """
        from deepseek_tui.engine.context import estimate_context_breakdown

        target_model = model or self.default_model
        try:
            api_tools = self.tool_registry.to_api_tools()
        except Exception:  # noqa: BLE001 — registry may raise during boot
            api_tools = []
        api_tools = self._initial_request_tools_for_context(api_tools)

        return estimate_context_breakdown(
            model=target_model,
            messages=self.session_messages or None,
            skills_context=self._render_skills_context(),
            api_tools=api_tools,
            workspace=self.tool_context.working_directory,
            mode=(self.mode or "agent").strip() or "agent",
            real_input_tokens=self.last_real_input_tokens,
        )

    async def context_breakdown_live(self, model: str | None = None) -> dict[str, int]:
        """Estimate context using the same tool catalog sent to the model.

        Unlike :meth:`context_breakdown`, this async path considers dynamically
        discovered MCP tools.

        Never blocks on cold MCP discovery — Workbench polls this endpoint and
        must not wait on subprocess startup.
        """
        from deepseek_tui.engine.context import estimate_context_breakdown

        target_model = model or self.default_model
        try:
            api_tools = await self._get_tools_with_mcp()
        except Exception:  # noqa: BLE001
            api_tools = []
        api_tools = self._initial_request_tools_for_context(api_tools)

        return estimate_context_breakdown(
            model=target_model,
            messages=self.session_messages or None,
            skills_context=self._render_skills_context(),
            api_tools=api_tools,
            workspace=self.tool_context.working_directory,
            mode=(self.mode or "agent").strip() or "agent",
            real_input_tokens=self.last_real_input_tokens,
        )

    def _initial_request_tools_for_context(
        self, api_tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Shallow-copy the catalog sent on the first request for token counts."""
        tools = [dict(tool) for tool in api_tools]
        for tool in tools:
            function = tool.get("function")
            if isinstance(function, dict):
                tool["function"] = dict(function)
        return tools

    async def shutdown(self) -> None:
        """Drain managers owned by the tool runtime if Engine built it."""
        await self.shutdown_session()
        try:
            await self.handle.emit(
                SessionEndedEvent(
                    session_id=self._cycle_session_id, turns=self.turn_counter
                )
            )
        except Exception:  # noqa: BLE001
            pass
        if hasattr(self.client, "close"):
            await self.client.close()

    async def run_single_turn(
        self,
        content: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        """Run one turn without ``run()``'s op loop or activity coordinator.

        Used by the task executor: shared TaskManager, no extra worker pool.
        """
        op = SendMessageOp(
            content=content,
            model=model,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        with bind_turn() as turn_id:
            self.handle.reset_cancel()
            if self.tool_context.subagent_manager is not None:
                self.tool_context.subagent_manager.attach_parent_cancel(
                    self.handle.cancel_event
                )
            self.handle._mark_turn_active()
            try:
                await self._handle_send_message_inner(op, turn_id)
            finally:
                self.handle._mark_turn_idle()

    async def run(self) -> None:
        logger.info(
            "engine_run_start model=%s session_id=%s",
            self.default_model,
            self._cycle_session_id,
        )
        self._activity_coordinator.start()
        await self.handle.emit(
            SessionStartedEvent(session_id=self._cycle_session_id)
        )
        turn_task: asyncio.Task[None] | None = None
        try:
            while True:
                if turn_task is not None and turn_task.done():
                    try:
                        turn_task.result()
                    except asyncio.CancelledError:
                        # Turn-scoped cancellation; TurnCancelledEvent already
                        # emitted by _handle_send_message. Not an engine error.
                        logger.info("engine_turn_task_cancelled")
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("engine_turn_task_failed")
                        await self.handle.emit(
                            ErrorEvent(
                                message=f"Internal engine error: {exc}",
                                retryable=False,
                            )
                        )
                    turn_task = None

                if turn_task is None:
                    op = await self.handle.next_op()
                else:
                    op_wait = asyncio.create_task(
                        self.handle.next_op(), name="engine-next-op"
                    )
                    done, _pending = await asyncio.wait(
                        {op_wait, turn_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if turn_task in done:
                        try:
                            turn_task.result()
                        except asyncio.CancelledError:
                            logger.info("engine_turn_task_cancelled")
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("engine_turn_task_failed")
                            await self.handle.emit(
                                ErrorEvent(
                                    message=f"Internal engine error: {exc}",
                                    retryable=False,
                                )
                            )
                        turn_task = None
                        if op_wait in done:
                            op = op_wait.result()
                        else:
                            op_wait.cancel()
                            try:
                                # Await so the task is reaped; it may still
                                # deliver an op that won the race vs cancel().
                                op = await op_wait
                            except asyncio.CancelledError:
                                continue
                    else:
                        op = op_wait.result()

                if isinstance(op, SendMessageOp):
                    if turn_task is not None:
                        await turn_task
                    turn_task = asyncio.create_task(
                        self._handle_send_message(op),
                        name="engine-turn",
                    )
                elif isinstance(op, CancelRequestOp):
                    logger.info("engine_cancel_request reason=%s", op.reason)
                    # Defense in depth: ensure the cancel_event is set even if
                    # the caller queued the op without calling handle.cancel().
                    self.handle.cancel_event.set()
                    if turn_task is not None and not turn_task.done():
                        turn_task.cancel()
        except asyncio.CancelledError:
            logger.info("engine_run_cancelled")
            raise
        finally:
            if turn_task is not None:
                turn_task.cancel()
                try:
                    await turn_task
                except asyncio.CancelledError:
                    pass
            await self._activity_coordinator.stop()

    async def _handle_send_message(self, op: SendMessageOp) -> None:
        with bind_turn() as turn_id:
            self.handle.reset_cancel()
            if self.tool_context.subagent_manager is not None:
                self.tool_context.subagent_manager.attach_parent_cancel(
                    self.handle.cancel_event
                )
            self.handle._mark_turn_active()
            # Publish the live auto-approve flag so task_create inherits the
            # session's actual approval mode (yolo/auto) instead of silently
            # defaulting. The Workbench thread manager writes the same key
            # per turn with the same value.
            self.tool_context.metadata["session_auto_approve"] = bool(
                await self.approval_handler.auto_approve_enabled()
            )
            try:
                await self._handle_send_message_inner(op, turn_id)
            except asyncio.CancelledError:
                # Hard cancellation (turn_task.cancel()) can interrupt the
                # turn at any await point, racing ahead of the cooperative
                # cancel_event path and skipping its TurnCancelledEvent.
                # Emit it here and swallow the error: the cancellation is
                # scoped to this turn, not to the engine run loop.
                reason = self.handle.cancel_reason or "user_cancelled"
                logger.info("turn_hard_cancelled reason=%s", reason)
                await self.handle.emit(TurnCancelledEvent(reason=reason))
                await self._finish_goal_turn(
                    cancelled=True,
                    failed=False,
                    error_message=reason,
                )
            except Exception as exc:
                await self._finish_goal_turn(
                    cancelled=False,
                    failed=True,
                    error_message=str(exc),
                )
                raise
            finally:
                self.handle._mark_turn_idle()

    def _expand_plugin_command(self, content: str) -> str | None:
        """Expand a ``/<plugin>:<command> [args]`` invocation, else ``None``.

        Matches a leading slash token that contains a ``:`` namespace (so it
        never collides with built-in ``/skill-name`` focus, which has no
        colon). Substitutes ``$ARGUMENTS`` / ``${ARGUMENTS}`` in the command
        body with the trailing arguments; appends any args when the template
        declares no placeholder.

        If the command's plugin hasn't been activated yet (deferred heavy
        assembly), activates it on-demand before looking up the body.
        """
        text = (content or "").strip()
        if not text.startswith("/") or ":" not in text.split(maxsplit=1)[0]:
            return None
        parts = text[1:].split(maxsplit=1)
        token = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        command = self.plugin_commands.get(token.lower())
        if command is None:
            # Deferred: activate the plugin on-demand, then retry.
            plugin_name = token.split(":", 1)[0]
            if any(n.lower() == plugin_name.lower() for n in self.plugin_names):
                self.ensure_plugin_activated(plugin_name)
                command = self.plugin_commands.get(token.lower())
        if command is None:
            return None
        body = command.body
        if "$ARGUMENTS" in body or "${ARGUMENTS}" in body:
            body = body.replace("${ARGUMENTS}", args).replace("$ARGUMENTS", args)
        elif args:
            body = f"{body}\n\n{args}"
        logger.info("plugin_command_expanded command=%s", command.qualified)
        return body

    async def _handle_send_message_inner(
        self, op: SendMessageOp, turn_id: str
    ) -> None:
        """
        同步沙箱策略、预处理用户输入、探测工具 profile / skill 聚焦模式 / 语言,
        把用户消息拼进会话历史并按模式(plan/中文)追加临时 hint,
        最后设置每轮工具白名单、发出 TurnStartedEvent 并存崩溃检查点,为下游真正跑 LLM 循环铺好前置状态
        """
        from deepseek_tui.policy.sandbox import sync_execution_sandbox_policy

        sync_execution_sandbox_policy(
            self.tool_context,
            self.mode,
            self.tool_context.working_directory,
        )
        # MCP 连接器聚焦：必须在 prepare_turn_for_model 之前检测，否则
        # prepare_turn_for_model 会把开头的 `@<连接器名>` 当作文件 mention
        # 展开，注入 <missing-file> 块（甚至内联同名工作区文件），污染
        # 上下文。skill 聚焦用 `/` 前缀无此冲突。命中时把首个 `@<name>`
        # token 剥掉再处理，处理完再拼回用户消息，模型仍能看到连接器线索。
        raw_content = op.content or ""
        # UserPromptSubmit（message_submit）hooks 在引擎层触发，所有 surface
        # （TUI/server/CLI）语义一致：阻断决策让 prompt 到不了模型；
        # additionalContext 作为 system reminder 注入（不改用户消息原文）。
        hook_context_extra = ""
        if not op.hidden:
            hook_results = await self.run_lifecycle_hook(
                "message_submit", message=raw_content
            )
            if hook_results:
                from deepseek_tui.integrations.hooks import aggregate_hook_decision

                decision = aggregate_hook_decision(hook_results)
                if decision.blocked:
                    reason = decision.reason or "blocked by a UserPromptSubmit hook"
                    snapshot = self.goal_service.snapshot()
                    if snapshot is not None and snapshot.status.value == "active":
                        from deepseek_tui.goal.types import GoalActor

                        self.goal_service.mark_blocked(
                            f"Blocked by UserPromptSubmit hook: {reason}",
                            actor=GoalActor.RUNTIME,
                        )
                    logger.info(
                        "user_prompt_blocked_by_hook reason=%r", reason[:200]
                    )
                    await self.handle.emit(
                        StatusEvent(
                            message=f"Message blocked by hook: {reason[:200]}"
                        )
                    )
                    await self.handle.emit(TurnStartedEvent(user_text=""))
                    await self.handle.emit(
                        TurnCompleteEvent(assistant_message=None, success=True)
                    )
                    return
                hook_context_extra = "\n".join(decision.additional_context)
        # 插件命令（/<plugin>:<command> [args]）：把命令 markdown 正文按
        # $ARGUMENTS 展开后替换成用户消息，随后照常走 @mention/聚焦处理。
        # 声明式文本，任何 surface（CLI/TUI/server）发进来都在此统一展开。
        expanded_cmd = self._expand_plugin_command(raw_content)
        if expanded_cmd is not None:
            raw_content = expanded_cmd
        # 插件挂载（@plugin:name / @plugin:off）：必须早于 _detect_focus_mcp，
        # 否则 `@plugin:x` 会被当成聚焦名为 `plugin` 的 MCP。命中则更新会话级
        # _active_plugin、剥掉前缀，本轮起即生效（持续态）。UI 只靠
        # PluginMountEvent（composer 底部徽章），不再发带 [plugin] 前缀的
        # StatusEvent，避免时间线重复系统气泡。
        plugin_mount = _detect_plugin_mount(raw_content)
        if plugin_mount is not None:
            mount_note = self.set_active_plugin(
                None if plugin_mount == "off" else plugin_mount
            )
            raw_content = _strip_plugin_mount(raw_content, plugin_mount)
            # Structured state change for the UI (persistent badge) and for
            # reload-restore. Only emit on a real transition: unmount always
            # clears; mount only when the plugin was actually found & applied.
            mounted = self._active_plugin
            if plugin_mount == "off":
                await self.handle.emit(PluginMountEvent(name=None, message=mount_note))
            elif mounted is not None and mounted.name.lower() == plugin_mount.lower():
                has_mcp = bool(mounted.manifest.mcp_servers)
                await self.handle.emit(
                    PluginMountEvent(
                        name=mounted.name,
                        version=mounted.manifest.version,
                        path=str(mounted.path.expanduser().resolve()),
                        scope=mounted.scope,
                        trusted=mounted.trusted,
                        permissions=mounted.manifest.permissions,
                        mcp_active=has_mcp and mounted.trusted,
                        message=mount_note,
                    )
                )
            else:
                # Mount failed (unknown plugin) — surface the error; do not
                # leave the UI assuming the scenario chip applied.
                await self.handle.emit(StatusEvent(message=mount_note))
            # Mount/unmount-only turn (no remaining user text): skip the LLM.
            if not (raw_content or "").strip():
                await self.handle.emit(
                    TurnStartedEvent(user_text="" if op.hidden else "")
                )
                await self.handle.emit(
                    TurnCompleteEvent(assistant_message=None, success=True)
                )
                return
        focus_mcp_ahead = _detect_focus_mcp(raw_content, self.mcp_manager)
        content_for_prepare = raw_content
        if focus_mcp_ahead is not None:
            content_for_prepare = _strip_focus_prefix(raw_content, "@", focus_mcp_ahead)
        processed = prepare_turn_for_model(
            content_for_prepare,
            workspace=self.tool_context.working_directory,
            session_id=self._cycle_session_id,
            turn_id=turn_id,
        )
        if focus_mcp_ahead is not None:
            # Re-prepend `@<name> ` so the model still sees the connector cue
            # in the user message — only file-mention expansion was suppressed.
            from dataclasses import replace as _dc_replace

            token_prefix = f"@{focus_mcp_ahead} "
            display = processed.display_text or ""
            model = processed.model_text or ""
            processed = _dc_replace(
                processed,
                display_text=f"{token_prefix}{display}".rstrip() if display else f"@{focus_mcp_ahead}",
                model_text=f"{token_prefix}{model}".rstrip() if model else f"@{focus_mcp_ahead}",
            )
        from deepseek_tui.engine.prompts import (
            TOOL_PROFILE_FULL,
            detect_tool_profile_from_prompt,
        )

        self.tool_profile = detect_tool_profile_from_prompt(
            processed.model_text or op.content or ""
        )
        if self.tool_profile == TOOL_PROFILE_FULL:
            self.tool_profile = None
        # Reset per-host timeout escalation so a prior turn's transient
        # network blip doesn't carry over (network_escalation counters are
        # meant to be turn-scoped, not session-scoped).
        from deepseek_tui.utils.network_escalation import reset_host_timeouts

        reset_host_timeouts(self.tool_context)

        # Skill 聚焦模式：若用户以 `/<skill-name>` 指定了一个已发现的 skill，
        # 本 turn 只列该 skill、只放最小工具集。未命中则 focus_skill 为 None，
        # 走原有全量逻辑（`/xxx` 当普通文本）。基于用户实际输入文本解析。
        focus_text = processed.display_text or op.content or ""
        focus_skill = _detect_focus_skill(focus_text, self.skill_registry)
        # MCP 连接器聚焦：已在 prepare_turn_for_model 之前预先检测（避免与
        # 文件 mention 展开冲突），此处复用结果。与 skill 聚焦互斥：skill
        # 命中时让位（首 token 不可能同时以 `/` 和 `@` 开头，互斥由构造保证）。
        focus_mcp = focus_mcp_ahead if focus_skill is None else None
        if focus_skill is not None:
            logger.info("skill_focus_mode skill=%s", getattr(focus_skill, "name", "?"))
        elif focus_mcp is not None:
            logger.info("mcp_focus_mode server=%s", focus_mcp)

        # Background subagent-done delivery re-enters as a hidden op whose
        # content is already an `<system-reminder>`-enveloped SUBAGENT_DONE
        # body (rendered at the idle-delivery site). It must carry the
        # SYSTEM_REMINDER provenance, not REAL_USER — otherwise a harness
        # injection reads back as the human's current request (origin drives
        # compaction, fake-reminder neutralization, and ledger classing).
        from deepseek_tui.goal.types import GOAL_CONTINUATION_KIND

        if op.internal_kind in (
            SUBAGENT_BACKGROUND_DONE_KIND,
            PROCESS_BACKGROUND_DONE_KIND,
        ):
            user_origin = MessageOrigin.SYSTEM_REMINDER
        elif op.internal_kind == GOAL_CONTINUATION_KIND:
            user_origin = MessageOrigin.GOAL_CONTINUATION
        else:
            user_origin = MessageOrigin.REAL_USER
        user_message = Message.user(processed.model_text, origin=user_origin)

        prior_count = len(self.session_messages)
        working_messages = [*self.session_messages, user_message]
        # The handoff reminder is volatile — inject as a user reminder before
        # the real query, never into the system prompt (KV cache).
        if not op.hidden:
            insert_at = prior_count
            snapshot_msg = self._take_git_snapshot_message()
            if snapshot_msg is not None:
                working_messages.insert(insert_at, snapshot_msg)
                insert_at += 1
            handoff_msg = self._take_handoff_reminder_message()
            if handoff_msg is not None:
                working_messages.insert(insert_at, handoff_msg)
                insert_at += 1
            if hook_context_extra:
                from deepseek_tui.engine import reminders

                working_messages.insert(
                    insert_at,
                    reminders.reminder_message(
                        reminders.PROMPT_SUBMIT_HOOK_CONTEXT,
                        "Context from UserPromptSubmit hooks:\n" + hook_context_extra,
                    ),
                )
        self.tool_context.metadata["engine_mode"] = self.mode
        self.goal_service.on_turn_started()
        from deepseek_tui.goal.types import GOAL_TURN_ID_KEY, GoalStatus

        snap = self.goal_service.snapshot()
        self.tool_context.metadata[GOAL_TURN_ID_KEY] = None if snap is None else snap.goal_id
        goal_reminder_message: Message | None = None
        goal_text = self.goal_service.reminder_text()
        if goal_text:
            from deepseek_tui.engine import reminders as goal_reminders
            spec = goal_reminders.GOAL_ACTIVE
            if snap is not None and snap.status is GoalStatus.PAUSED:
                spec = goal_reminders.GOAL_PAUSED
            elif snap is not None and snap.status is GoalStatus.BLOCKED:
                spec = goal_reminders.GOAL_BLOCKED
            goal_reminder_message = goal_reminders.reminder_message(spec, goal_text)
            working_messages.append(goal_reminder_message)
        goal_deadline_task: asyncio.Task[None] | None = None
        if (
            snap is not None
            and snap.status is GoalStatus.ACTIVE
            and snap.budget.remaining_wall_clock_ms is not None
        ):
            goal_deadline_task = asyncio.create_task(
                self._enforce_goal_wall_clock_deadline(
                    snap.goal_id,
                    snap.budget.remaining_wall_clock_ms,
                ),
                name="goal-wall-clock-deadline",
            )
        self.working_set.observe_user_message(processed.display_text or "")
        self.working_set.observe_references(processed.references)
        preview = (processed.display_text or "")[:200].replace("\n", " ")
        logger.info(
            "turn_start user_text_len=%d model_text_len=%d preview=%r model=%s session_msgs=%d",
            len(processed.display_text or ""),
            len(processed.model_text or ""),
            preview,
            op.model or self.default_model,
            len(self.session_messages),
        )
        response_id = f"resp-{uuid.uuid4().hex[:12]}"
        self.handle.set_response_id(response_id)
        start = time.monotonic()

        # Plan mode: detect quick-plan requests that skip codebase exploration
        # and inject a grounding hint
        if should_force_update_plan_first(self.mode, processed.display_text or ""):
            from deepseek_tui.engine import reminders
            from deepseek_tui.engine.prompts import PLAN_GROUNDING_REMINDER

            working_messages.append(
                reminders.reminder_message(
                    reminders.PLAN_NUDGE, PLAN_GROUNDING_REMINDER
                )
            )
        from deepseek_tui.tools.plan_mode import sync_approved_plan_reminder

        sync_approved_plan_reminder(
            working_messages,
            mode=self.mode,
            working_directory=self.tool_context.working_directory,
            metadata=self.tool_context.metadata,
        )

        mode_hint = ""

        try:
            # 聚焦模式：置位 per-turn 工具白名单，``_get_tools_with_mcp`` 据此
            # 收窄 catalog。在 finally 中复位，异常/取消也不会泄漏到下一 turn。
            # skill：``FOCUS_SKILL_BASE`` ∪ ``allowed-tools``（并集，可扩
            # task 等）。MCP：``FOCUS_MCP_BASE`` ∪ 该 server 工具。
            # 显式前缀（/skill、@mcp）优先级最高；两者都未命中且挂载了插件时，
            # 回退到插件白名单（持续态）。都无 -> 全量（None）。
            if focus_skill is not None:
                declared = getattr(focus_skill, "allowed_tools", None)
                allowed = set(FOCUS_SKILL_BASE)
                if declared:
                    allowed |= set(declared)
                self._focus_tool_whitelist = frozenset(allowed)
                self._focus_allowed_servers = frozenset()
            elif focus_mcp is not None:
                mcp_mgr = self.mcp_manager
                focus_ready = True
                if mcp_mgr is not None:
                    ensure = getattr(mcp_mgr, "ensure_focus_server_discovered", None)
                    if callable(ensure):
                        try:
                            await ensure(focus_mcp)
                        except Exception as exc:  # noqa: BLE001
                            focus_ready = False
                            await self.handle.emit(
                                StatusEvent(message=f"连接器未就绪：{exc}")
                            )
                if focus_ready:
                    # Drop progressive MCP cache so this turn rebuilds with focus tools.
                    self._mcp_tools_cache = None
                    tools, servers = self._mcp_focus_whitelist(focus_mcp)
                    self._focus_tool_whitelist = tools
                    self._focus_allowed_servers = servers
                else:
                    self._focus_tool_whitelist = None
                    self._focus_allowed_servers = None
            elif self._active_plugin is not None:
                wl_result = self._active_plugin_whitelist()
                if wl_result is not None:
                    self._focus_tool_whitelist, self._focus_allowed_servers = (
                        wl_result
                    )
                else:
                    self._focus_tool_whitelist = None
                    self._focus_allowed_servers = None
                # Read-only放行插件自身目录（工作区外），让模型能 read_file/
                # file_search/grep 插件的 skill/清单等资源；写工具仍锁工作区。
                # 将来 skills 的 companion-file 根可在此 append。
                self.tool_context.extra_read_roots = (
                    self._active_plugin.path.expanduser().resolve(),
                )
            else:
                self._focus_tool_whitelist = None
                self._focus_allowed_servers = None
            await self.handle.emit(
                TurnStartedEvent(user_text="" if op.hidden else processed.display_text)
            )
            self.turn_usage_ledger.reset()
            self._goal_accounted_output_tokens = 0
            checkpoint_messages = [
                message
                for message in working_messages
                if message is not goal_reminder_message
            ]
            self._save_crash_checkpoint(
                checkpoint_messages,
                model=op.model or self.default_model,
            )
            sys_prompt = build_system_prompt(
                op.system_prompt,
                mode=_resolve_app_mode(self.mode),
                # Skill focus narrows the tool whitelist, not the catalog.
                # Rewriting ## Skills for a single turn costs two full prefix
                # cache misses (this turn, then the turn that reverts), and
                # the model does not need it: the user's `/<skill>` prefix is
                # never stripped from the message text, so the cue survives.
                # Plugin mount stays narrowed — it is session-level state, so
                # its prefix is stable across turns.
                skills_context=self._render_skills_context(
                    only=self._active_plugin_skills()
                    if focus_mcp is None and self._active_plugin is not None
                    else None
                ),
                plugin_context=(
                    self._render_plugin_context()
                    if focus_mcp is None and self._active_plugin is not None
                    else None
                ),
                plugin_components_context=self._render_plugin_components_context(),
                plugin_rules_context=self._render_plugin_rules_context(),
                workspace=self.tool_context.working_directory,
                locale_tag=self.reply_locale,
                automations_guidelines=self.tool_registry.contains("cron_create"),
            )
            if mode_hint:
                sys_prompt += mode_hint
            # Compaction bridges live in session_messages (leading user
            # message), not in the system prompt — mutating system every
            # compact would destroy the stable KV prefix cache.
            result = await self._run_conversation(
                messages=working_messages,
                model=op.model or self.default_model,
                system_prompt=sys_prompt,
                max_tokens=op.max_tokens,
                reasoning_effort=op.reasoning_effort,
            )

            duration_ms = int((time.monotonic() - start) * 1000)
            if result.cancelled:
                logger.info(
                    "turn_cancelled turn=%s duration_ms=%d reason=%s",
                    turn_id,
                    duration_ms,
                    self.handle.cancel_reason or "user_cancelled",
                )
                # Even on cancel, if the provider returned a StreamDone
                # before the cancel landed, result.usage is a valid pressure
                # reading — more accurate than the char-based estimate.
                # Record it so the next turn's should_compact /
                # cycle decisions aren't forced back to the ~6x-
                # undercounting estimate. If no usage arrived (cancel too
                # early), keep the previous value rather than zeroing — a
                # stale-but-real reading beats falling back to the estimate.
                cancelled_usage = result.usage
                cancelled_input = getattr(
                    cancelled_usage, "total_input_tokens", 0
                )
                if cancelled_input:
                    self.last_real_input_tokens = cancelled_input
                await self._emit_checklist_turn_end_reconcile()
                await self.handle.emit(
                    TurnCancelledEvent(
                        reason=self.handle.cancel_reason or "user_cancelled"
                    )
                )
                await self._finish_goal_turn(
                    cancelled=True,
                    failed=False,
                    error_message=self.handle.cancel_reason,
                )
                return

            from deepseek_tui.engine.turn import TurnOutcomeStatus

            turn_ok = result.outcome == TurnOutcomeStatus.SUCCESS
            # Only persist the turn's messages on success. Failed turns
            # (stream timeout, content overflow, ...) can leave a partial
            # assistant message in working_messages; persisting it would
            # corrupt the context for every later turn. Matches the
            # cancelled path above, which also discards working state.
            if turn_ok:
                persisted_messages = [
                    message
                    for message in working_messages
                    if message is not goal_reminder_message
                ]
                if op.hidden:
                    self.session_messages = [
                        *self.session_messages,
                        *persisted_messages[prior_count + 1 :],
                    ]
                else:
                    self.session_messages = persisted_messages
            if not result.cancelled:
                from deepseek_tui.state.session import clear_checkpoint

                clear_checkpoint()
            usage = result.usage
            # Backstop: _run_conversation already refreshes this after every
            # round; keep the turn-end write for paths whose result.usage is
            # synthesized outside the round loop. result.usage is the final
            # round's StreamDone usage, which is the largest input of the
            # turn (messages only grow between rounds).
            turn_input_tokens = getattr(usage, "total_input_tokens", 0)
            if turn_input_tokens:
                self.last_real_input_tokens = turn_input_tokens
            ledger_totals = self.turn_usage_ledger.totals()
            combined_usage = self.turn_usage_ledger.combined_usage()
            if combined_usage is not None:
                usage = combined_usage
            logger.info(
                "turn_complete duration_ms=%d input_tokens=%s output_tokens=%s "
                "cache_hit=%s reasoning_tokens=%s last_round_tool_calls=%d "
                "tool_rounds=%d metered_llm_calls=%d",
                duration_ms,
                ledger_totals.get("input_tokens", 0) or (getattr(usage, "input_tokens", 0) if usage else 0),
                ledger_totals.get("output_tokens", 0) or (getattr(usage, "output_tokens", 0) if usage else 0),
                ledger_totals.get("cache_hit_tokens", 0) or (getattr(usage, "cache_read_input_tokens", 0) if usage else 0),
                getattr(usage, "reasoning_tokens", 0) if usage else 0,
                len(result.tool_calls or []),
                result.tool_round_count,
                ledger_totals.get("turns", 0),
            )
            # Accumulate session cost from the DeepSeek usage payload.
            # Hidden when pricing is unknown (off-platform providers,
            # unrecognised model) — the UI also hides the chip in that
            # case so we don't show $0.00 misleadingly.
            cache_hit_tokens = 0
            cache_miss_tokens = 0
            cost_usd: float | None = None
            cost_cny: float | None = None
            turn_cache_hit = ledger_totals.get("cache_hit_tokens", 0)
            turn_cache_miss = ledger_totals.get("cache_miss_tokens", 0)
            if turn_cache_hit > 0 or turn_cache_miss > 0 or usage is not None:
                self.session_cache_hit_total += turn_cache_hit
                self.session_cache_miss_total += turn_cache_miss
                cache_hit_tokens = self.session_cache_hit_total
                cache_miss_tokens = self.session_cache_miss_total
                turn_cost_usd = ledger_totals.get("cost_usd")
                turn_cost_cny = ledger_totals.get("cost_cny")
                if isinstance(turn_cost_usd, (int, float)) and turn_cost_usd > 0:
                    self.session_cost_usd += float(turn_cost_usd)
                    cost_usd = self.session_cost_usd
                if isinstance(turn_cost_cny, (int, float)) and turn_cost_cny > 0:
                    self.session_cost_cny += float(turn_cost_cny)
                    cost_cny = self.session_cost_cny
            running_subagents = 0
            running_tasks = 0
            if self.tool_context.subagent_manager is not None:
                running_subagents = self.tool_context.subagent_manager.running_count()
            if self.tool_context.task_manager is not None:
                running_tasks = self.tool_context.task_manager.running_count()
            await self._emit_checklist_turn_end_reconcile()
            await self.handle.emit(
                TurnCompleteEvent(
                    assistant_message=result.assistant_message,
                    usage=combined_usage if combined_usage is not None else result.usage,
                    success=turn_ok,
                    error_message=None if turn_ok else result.error_message,
                    session_cost_usd=cost_usd,
                    session_cost_cny=cost_cny,
                    cache_hit_tokens=cache_hit_tokens,
                    cache_miss_tokens=cache_miss_tokens,
                    running_subagents=running_subagents,
                    running_tasks=running_tasks,
                )
            )
            await self._auto_persist_session()
            await self._finish_goal_turn(
                cancelled=False,
                failed=not turn_ok,
                error_message=None if turn_ok else result.error_message,
            )
            if not result.cancelled:
                self._user_turn_index += 1
        finally:
            if goal_deadline_task is not None:
                goal_deadline_task.cancel()
                with suppress(asyncio.CancelledError):
                    await goal_deadline_task
            self.handle.clear_response_id()
            # Disconnect on_focus media connectors after the turn so they never
            # linger in preload / progressive catalog.
            focused_servers = self._focus_allowed_servers
            # 复位聚焦模式白名单，确保不跨 turn 保留。
            self._focus_tool_whitelist = None
            self._focus_allowed_servers = None
            # 同理复位只读放行根：仅在挂载插件的 turn 内有效，取消/异常也不泄漏。
            self.tool_context.extra_read_roots = ()
            mcp_mgr = self.mcp_manager
            if focused_servers and mcp_mgr is not None:
                release = getattr(mcp_mgr, "release_focus_server", None)
                if callable(release):
                    for server in focused_servers:
                        try:
                            await release(server)
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "mcp_focus_release_failed server=%s", server
                            )
                self._mcp_tools_cache = None

    def _completion_agent_is_background(self, agent_id: str) -> bool:
        """True when *agent_id* is a ``run_in_background`` child still known."""
        mgr = self.tool_context.subagent_manager
        if mgr is None:
            return False
        agent = mgr._agents.get(agent_id)  # noqa: SLF001 — engine owns manager
        return bool(agent is not None and getattr(agent, "background", False))

    def _enqueue_subagent_completion(self, completion: SubAgentCompletion) -> None:
        """Thread-safe enqueue from sub-agent driver tasks (#756).

        For ``run_in_background`` children, also schedules idle delivery so
        results that arrive after the parent turn ends still reach the LLM via
        a hidden follow-up turn (Kimi-style automatic notification). Foreground
        completions stay on the handoff path only.
        """
        if completion.agent_id in self._consumed_subagent_completions:
            return
        try:
            self._subagent_completions.put_nowait(completion)
        except asyncio.QueueFull:
            logger.error(
                "subagent_completion_dropped agent_id=%s queue_full=64 — "
                "handoff waiters may stall until timeout",
                completion.agent_id,
            )
            return
        if self._completion_agent_is_background(completion.agent_id):
            self._schedule_idle_subagent_completion_delivery()

    def _schedule_idle_subagent_completion_delivery(self) -> None:
        """Coalesce pending completions into a hidden turn once the engine is idle."""
        task = getattr(self, "_idle_subagent_delivery_task", None)
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._idle_subagent_delivery_task = loop.create_task(
            self._deliver_subagent_completions_when_idle(),
            name="subagent-idle-completion-delivery",
        )

    async def _deliver_subagent_completions_when_idle(self) -> None:
        """If the parent turn already ended, inject pending sub-agent results.

        Active-turn completions are still handled by
        ``_handle_subagent_turn_handoff`` (which drains the same queue). This
        path only fires when the engine is idle so background agents do not
        leave orphaned ``<deepseek:subagent.done>`` payloads in the queue.
        """
        # Wait out the current turn (handoff may still drain the queue).
        for _ in range(12_000):  # ~10 min at 50ms
            if not self.handle.is_turn_active():
                break
            await asyncio.sleep(0.05)
        else:
            logger.warning("subagent_idle_delivery_gave_up turn_still_active")
            return
        # Brief coalesce window for siblings finishing together.
        await asyncio.sleep(0.05)
        if self.handle.is_turn_active():
            self._schedule_idle_subagent_completion_delivery()
            return
        completions = self._drain_subagent_completions()
        if not completions:
            return
        for item in completions:
            self._consumed_subagent_completions.add(item.agent_id)
        from deepseek_tui.engine import reminders

        parts: list[str] = []
        ledger = await self._subagent_handoff_ledger(completions)
        if ledger:
            rendered = reminders.render(reminders.SUBAGENT_HANDOFF, ledger)
            if rendered:
                parts.append(rendered)
        parts.extend(
            reminders.render(reminders.SUBAGENT_DONE, item.payload)
            for item in completions
        )
        body = "\n\n".join(part for part in parts if part)
        logger.info(
            "subagent_idle_delivery count=%d",
            len(completions),
        )
        await self.handle.send_op(
            SendMessageOp(
                content=body,
                hidden=True,
                internal_kind=SUBAGENT_BACKGROUND_DONE_KIND,
            )
        )

    async def _subagent_handoff_ledger(
        self, completions: list[SubAgentCompletion]
    ) -> str | None:
        """Batch scorecard for the parent. ``None`` when a ledger would be noise."""
        mgr = self.tool_context.subagent_manager
        if mgr is None or not completions:
            return None
        from deepseek_tui.tools.subagent.handoff_ledger import build_handoff_ledger

        snaps = []
        for item in completions:
            try:
                snaps.append(await mgr.get_result(item.agent_id))
            except KeyError:
                continue
        return build_handoff_ledger(snaps)

    def _drain_subagent_completions(self) -> list[SubAgentCompletion]:
        out: list[SubAgentCompletion] = []
        while True:
            try:
                completion = self._subagent_completions.get_nowait()
            except asyncio.QueueEmpty:
                break
            if completion.agent_id in self._consumed_subagent_completions:
                continue
            out.append(completion)
        return out

    def _enqueue_shell_process_completion(self, payload: dict[str, Any]) -> None:
        """Thread-safe enqueue when a background shell process exits."""
        process_id = payload.get("process_id")
        if not isinstance(process_id, str):
            return
        if process_id in self._consumed_process_completions:
            return
        try:
            self._process_completions.put_nowait(payload)
        except asyncio.QueueFull:
            logger.error(
                "shell_process_completion_dropped process_id=%s queue_full=64",
                process_id,
            )
            return
        self._schedule_idle_process_completion_delivery()

    def _schedule_idle_process_completion_delivery(self) -> None:
        task = getattr(self, "_idle_process_delivery_task", None)
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._idle_process_delivery_task = loop.create_task(
            self._deliver_process_completions_when_idle(),
            name="shell-idle-completion-delivery",
        )

    async def _deliver_process_completions_when_idle(self) -> None:
        """Inject pending background-shell results once the engine is idle."""
        for _ in range(12_000):  # ~10 min at 50ms
            if not self.handle.is_turn_active():
                break
            await asyncio.sleep(0.05)
        else:
            logger.warning("process_idle_delivery_gave_up turn_still_active")
            return
        await asyncio.sleep(0.05)
        if self.handle.is_turn_active():
            self._schedule_idle_process_completion_delivery()
            return
        completions = self._drain_process_completions()
        if not completions:
            return
        for item in completions:
            process_id = item.get("process_id")
            if isinstance(process_id, str):
                self._consumed_process_completions.add(process_id)
        from deepseek_tui.engine import reminders

        body = "\n\n".join(
            reminders.render(reminders.PROCESS_DONE, _format_process_done(item))
            for item in completions
        )
        logger.info("process_idle_delivery count=%d", len(completions))
        await self.handle.send_op(
            SendMessageOp(
                content=body,
                hidden=True,
                internal_kind=PROCESS_BACKGROUND_DONE_KIND,
            )
        )

    def _drain_process_completions(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while True:
            try:
                payload = self._process_completions.get_nowait()
            except asyncio.QueueEmpty:
                break
            process_id = payload.get("process_id")
            if isinstance(process_id, str) and process_id in self._consumed_process_completions:
                continue
            out.append(payload)
        return out

    def _mark_process_tool_result_consumed(
        self,
        tool_name: str,
        metadata: dict[str, Any] | None,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        """Drop idle notification when task_output/task_stop already collected."""
        if tool_name not in ("task_output", "task_stop"):
            return
        if not isinstance(arguments, dict) or not arguments.get("process_id"):
            return
        if not isinstance(metadata, dict):
            return
        process_id = metadata.get("process_id")
        status = metadata.get("status")
        if isinstance(process_id, str) and status in {"completed", "cancelled"}:
            self._consumed_process_completions.add(process_id)

    def _mark_subagent_tool_result_consumed(
        self,
        tool_name: str,
        metadata: dict[str, Any] | None,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        """Mark sub-agent completions already returned by wait/result tools."""
        if not isinstance(metadata, dict):
            return

        if tool_name == "agent_resume":
            agent_id = metadata.get("agent_id")
            if isinstance(agent_id, str):
                self._consumed_subagent_completions.discard(agent_id)
            return

        if tool_name == "agent":
            # A resume restarts the agent: its next completion must arrive
            # fresh, not be swallowed as already-consumed (same handling as
            # the retired agent_resume tool above).
            if isinstance(arguments, dict):
                resume_id = arguments.get("resume")
                if isinstance(resume_id, str) and resume_id:
                    self._consumed_subagent_completions.discard(resume_id)
                    return
            # Only the result/cancel/wait actions return terminal snapshots;
            # list would wrongly swallow pending completion reminders.
            # (result/cancel are retired actions now, but legacy calls keep
            # arriving under the original name — normalization happens after
            # this marking sees the call.)
            action = arguments.get("action") if isinstance(arguments, dict) else None
            if action not in ("result", "cancel", "wait"):
                return
        elif tool_name in ("task_output", "task_stop"):
            # Unified read/stop tools took over the retired agent
            # result/cancel actions: only their agent_id branch returns a
            # terminal sub-agent snapshot (task_id/process_id branches must
            # not consume anything).
            if not isinstance(arguments, dict) or not arguments.get("agent_id"):
                return
        else:
            return

        def terminal_agent_id(raw: object) -> str | None:
            if not isinstance(raw, dict):
                return None
            agent_id = raw.get("agent_id")
            status = raw.get("status")
            if not isinstance(agent_id, str) or not isinstance(status, dict):
                return None
            kind = status.get("kind")
            if kind in {"completed", "failed", "cancelled", "interrupted"}:
                return agent_id
            return None

        agents = metadata.get("agents")
        consumed: set[str] = set()
        if isinstance(agents, list):
            for raw in agents:
                agent_id = terminal_agent_id(raw)
                if agent_id is not None:
                    consumed.add(agent_id)
        else:
            agent_id = terminal_agent_id(metadata)
            if agent_id is not None:
                consumed.add(agent_id)

        self._consumed_subagent_completions.update(consumed)

    def _open_checklist_summary(self) -> str:
        """Short summary of open checklist items, or "" when none are open.

        Reads the shared in-memory checklist store on
        ``tool_context.metadata['todos']`` (see :mod:`deepseek_tui.tools.todo`).
        "Open" = ``pending`` or ``in_progress``; ``completed`` and
        ``cancelled`` do not count. Empty string means the turn-end gate
        should not fire (no checklist, or everything resolved).
        """
        if self.tool_context is None:
            return ""
        store = self.tool_context.metadata.get("todos")
        if not isinstance(store, dict):
            return ""
        items = store.get("items")
        if not isinstance(items, list):
            return ""
        open_items = [
            it
            for it in items
            if getattr(it, "status", None) in ("pending", "in_progress")
        ]
        if not open_items:
            return ""
        return ", ".join(
            f"#{getattr(it, 'id', '?')} {getattr(it, 'status', '?')}"
            for it in open_items
        )

    def _next_checklist_gate_summary(
        self, *, fired: int, last_open: str | None
    ) -> str | None:
        """Open-item summary to block on, or ``None`` to let the turn end.

        The gate re-fires only while blocking it moves the checklist forward:
        *last_open* is the open set as of the previous block, so an unchanged
        set means the last nudge produced nothing and the model's decision to
        stop is honored. That keeps "unfinished work should continue" without
        the livelock a fire-until-empty gate would have — the harness cannot
        judge completion, only the model can, and one that will not reconcile
        would otherwise spin to the round-trip limit.
        """
        if fired >= _CHECKLIST_GATE_MAX_FIRES:
            return None
        open_summary = self._open_checklist_summary()
        if not open_summary or open_summary == last_open:
            return None
        return open_summary

    async def _emit_checklist_turn_end_reconcile(self) -> None:
        """Close leftover open checklist items before the turn goes idle.

        After the single-shot gate, a weak model may still stop with
        ``pending`` / ``in_progress`` rows. Cancel those so Workbench never
        keeps a spinning todo card on an idle turn. Emits a synthetic
        checklist tool pair so the snapshot reaches the timeline.
        """
        if self.tool_context is None:
            return
        from deepseek_tui.tools.todo import reconcile_open_checklist_items

        reconciled = reconcile_open_checklist_items(self.tool_context)
        if reconciled is None:
            return
        content, metadata = reconciled
        tool_call_id = f"checklist_reconcile_{uuid.uuid4().hex[:8]}"
        await self.handle.emit(
            ToolCallEvent(
                tool_call=ToolCall(
                    id=tool_call_id,
                    name="checklist",
                    arguments={"op": "update", "reason": "turn_end_reconcile"},
                )
            )
        )
        await self.handle.emit(
            ToolResultEvent(
                tool_call_id=tool_call_id,
                tool_name="checklist",
                content=content,
                success=True,
                metadata=metadata,
            )
        )
        logger.info("checklist_turn_end_reconcile")

    async def _handle_subagent_turn_handoff(self, messages: list[Message]) -> bool:
        """Wait for direct children and inject ``<deepseek:subagent.done>`` (#756).

        Returns True when completions were injected and the turn should continue.
        """
        mgr = self.tool_context.subagent_manager
        if mgr is None:
            return False

        completions = self._drain_subagent_completions()
        running = mgr.running_foreground_count()
        if running > 0:
            await self.handle.emit(
                StatusEvent(
                    message=f"Waiting on {running} sub-agent(s) to complete..."
                )
            )
            deadline = time.monotonic() + mgr.handoff_timeout_secs
            timed_out = False
            while running > 0:
                if self.handle.cancel_event.is_set():
                    # Hard cancel: do not inject; caller aborts the turn.
                    return False
                if time.monotonic() > deadline:
                    timed_out = True
                    logger.warning(
                        "subagent_handoff_timeout running=%d collected=%d",
                        running,
                        len(completions),
                    )
                    break
                try:
                    completion = await asyncio.wait_for(
                        self._subagent_completions.get(), timeout=0.25
                    )
                    if completion.agent_id not in self._consumed_subagent_completions:
                        completions.append(completion)
                except asyncio.TimeoutError:
                    pass
                completions.extend(self._drain_subagent_completions())
                running = mgr.running_foreground_count()
            if timed_out:
                completions.extend(self._drain_subagent_completions())
        else:
            completions.extend(self._drain_subagent_completions())

        if not completions:
            return False

        count = len(completions)
        from deepseek_tui.engine import reminders

        ledger = await self._subagent_handoff_ledger(completions)
        if ledger:
            messages.append(
                reminders.reminder_message(reminders.SUBAGENT_HANDOFF, ledger)
            )
        for item in completions:
            # Mark consumed so idle-delivery cannot re-inject the same payload
            # if a race schedules a wake after this handoff drains the queue.
            self._consumed_subagent_completions.add(item.agent_id)
            messages.append(
                reminders.reminder_message(reminders.SUBAGENT_DONE, item.payload)
            )
        await self.handle.emit(
            StatusEvent(
                message=f"Resuming turn with {count} sub-agent completion(s)"
            )
        )
        logger.info("subagent_handoff count=%d", count)
        return True

    async def _handle_shell_process_turn_handoff(
        self, messages: list[Message]
    ) -> bool:
        """Wait for non-detached background shells and inject their results.

        The shell counterpart of :meth:`_handle_subagent_turn_handoff`. Without
        it a foreground command that the timeout re-homed into the background
        never reaches the model: the turn ends, the op-loop consumer goes away
        (single-turn CLI cancels it outright), and the idle delivery path posts
        ``PROCESS_DONE`` into a queue nobody reads. Blocking here keeps the
        engine alive until the result exists, which is what ``exec_shell``
        already promises ("you are notified when they finish").

        Only ``detached=False`` processes hold the turn — an explicit
        ``background=true`` server or watcher is excluded by
        ``running_attached_count`` and still arrives via idle delivery.

        Returns True when completions were injected and the turn should continue.
        """
        from deepseek_tui.tools.shell import running_attached_count

        completions = self._drain_process_completions()
        try:
            running = running_attached_count(self.tool_context)
        except Exception:  # noqa: BLE001
            running = 0
        if running > 0:
            await self.handle.emit(
                StatusEvent(
                    message=f"Waiting on {running} background shell process(es)..."
                )
            )
            # Deliberately shorter than the sub-agent handoff budget: a shell
            # already burned up to EXEC_MAX_TIMEOUT_MS (600s) in the
            # foreground, so a second 600s wait would stall a turn for 20
            # minutes. The process keeps running past this bound; only the
            # in-turn wait gives up, and idle delivery still fires.
            deadline = time.monotonic() + SHELL_HANDOFF_TIMEOUT_SECS
            while running > 0:
                if self.handle.cancel_event.is_set():
                    # Hard cancel: do not inject; caller aborts the turn.
                    return False
                if time.monotonic() > deadline:
                    logger.warning(
                        "shell_handoff_timeout running=%d collected=%d",
                        running,
                        len(completions),
                    )
                    break
                try:
                    payload = await asyncio.wait_for(
                        self._process_completions.get(), timeout=0.25
                    )
                    process_id = payload.get("process_id")
                    if (
                        not isinstance(process_id, str)
                        or process_id not in self._consumed_process_completions
                    ):
                        completions.append(payload)
                except asyncio.TimeoutError:
                    pass
                completions.extend(self._drain_process_completions())
                running = running_attached_count(self.tool_context)
            completions.extend(self._drain_process_completions())

        if not completions:
            return False

        from deepseek_tui.engine import reminders

        for item in completions:
            # Mark consumed so idle delivery cannot re-inject the same payload
            # if a race schedules a wake after this handoff drains the queue.
            process_id = item.get("process_id")
            if isinstance(process_id, str):
                self._consumed_process_completions.add(process_id)
            messages.append(
                reminders.reminder_message(
                    reminders.PROCESS_DONE, _format_process_done(item)
                )
            )
        count = len(completions)
        await self.handle.emit(
            StatusEvent(
                message=f"Resuming turn with {count} shell result(s)"
            )
        )
        logger.info("shell_handoff count=%d", count)
        return True

    def _log_prefix_break(
        self,
        round_idx: int,
        system_prompt: str | None,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
    ) -> None:
        """Name whatever invalidated the provider's KV prefix this round.

        ``prefix_cache`` already reports the hit ratio, but a ratio alone cannot
        say which of compaction, L0 pruning, reminder injection or an unstable
        tool schema moved history. Comparing per-unit digests against the last
        round does: the first mismatch is the culprit, and everything after it
        is re-billed at full price. Silence means the round was a pure append.

        One hashing pass over history — ~3ms on an 800-message, 600k-char
        session, so it rides the log level rather than a separate switch.
        """
        if not logger.isEnabledFor(logging.INFO):
            return
        from deepseek_tui.engine.prefix_probe import (
            describe_break,
            fingerprint_request,
            first_divergence,
        )

        digests = fingerprint_request(system_prompt, messages, tools)
        previous, self._prefix_digests = self._prefix_digests, digests
        if not previous:
            return
        break_at = first_divergence(previous, digests)
        if break_at is None:
            return
        logger.info(
            "prefix_break round=%d at=%d/%d reusable=%.0f%% culprit=%s",
            round_idx,
            break_at,
            len(previous),
            break_at / len(previous) * 100,
            describe_break(break_at, messages),
        )

    async def _run_conversation(
        self,
        messages: list[Message],
        model: str,
        system_prompt: str,
        max_tokens: int | None,
        reasoning_effort: str | None = None,
    ) -> TurnResult:
        """
        是单个 turn 的核心工具循环——最多跑 max_tool_round_trips+1 轮,
        每轮先做各种上下文维护(cycle 归档、drain 中途转向的 steer 消息、容量预检查、超阈值就压缩历史、刷 LSP 诊断),
        再带上工具向 LLM 发一次请求;若模型回工具调用就执行工具、把结果塞回消息列表进入下一轮,直到模型给出最终答案(或触发取消/错误上限),返回 TurnResult
        """
        tools = await self._get_tools_with_mcp()
        self.turn_counter += 1
        self._tool_dedup.reset_turn()
        step_error_count = 0
        consecutive_tool_error_steps = 0
        # Cycle boundary check (opt-in). When the active input grows past
        # ``cycle_config.threshold_for(model)``, archive the cycle to disk
        # and continue with a trimmed message list. Best-effort — failures
        # never block the conversation.
        # 输入逼近窗口上限时，归档全量历史到磁盘、只留最近 8 条继续
        if self.cycle_config.enabled:
            await self._maybe_advance_cycle(
                messages, model, system_prompt=system_prompt, tools=tools
            )
        turn_id = self.tool_context.metadata.get("turn_latency_turn_id")
        from deepseek_tui.server.metrics import get_turn_latency

        latency_turn_id = str(turn_id) if turn_id else None
        tool_round_count = 0
        # True once a turn_end (Claude "Stop") hook has blocked the stop —
        # delivered to hooks as ``stop_hook_active`` so they can avoid
        # blocking forever. ``_STOP_HOOK_MAX_FIRES`` is the backstop for hooks
        # that block anyway; the round-trip limit is the last resort.
        stop_hook_active = False
        stop_hook_fires = 0
        # Checklist turn-end gate bookkeeping. The gate blocks ending the turn
        # while the model keeps resolving open items and releases as soon as a
        # block changes nothing (see _next_checklist_gate_summary). It never
        # judges whether the work is actually done — that stays the model's
        # call, preserving the completion gate.
        checklist_gate_fires = 0
        checklist_gate_last_open: str | None = None
        for round_idx in range(self.max_tool_round_trips + 1):
            trace = get_turn_latency(latency_turn_id) if latency_turn_id else None
            round_trace = trace.start_round(round_idx) if trace is not None else None
            logger.info(
                "round_start round=%d msg_count=%d tools_count=%d model=%s",
                round_idx,
                len(messages),
                len(tools),
                model,
            )
            # Drain steer messages — mid-turn user input
            # 这是中途转向机制
            for steer_text in self.handle.drain_steers():
                steer_text = steer_text.strip()
                if not steer_text:
                    continue
                # Honor @plugin: mount/unmount in steers (same as primary send).
                plugin_mount = _detect_plugin_mount(steer_text)
                if plugin_mount is not None:
                    mount_note = self.set_active_plugin(
                        None if plugin_mount == "off" else plugin_mount
                    )
                    steer_text = _strip_plugin_mount(steer_text, plugin_mount)
                    mounted = self._active_plugin
                    if plugin_mount == "off":
                        await self.handle.emit(
                            PluginMountEvent(name=None, message=mount_note)
                        )
                    elif (
                        mounted is not None
                        and mounted.name.lower() == plugin_mount.lower()
                    ):
                        has_mcp = bool(mounted.manifest.mcp_servers)
                        await self.handle.emit(
                            PluginMountEvent(
                                name=mounted.name,
                                version=mounted.manifest.version,
                                path=str(mounted.path.expanduser().resolve()),
                                scope=mounted.scope,
                                trusted=mounted.trusted,
                                permissions=mounted.manifest.permissions,
                                mcp_active=has_mcp and mounted.trusted,
                                message=mount_note,
                            )
                        )
                    else:
                        await self.handle.emit(StatusEvent(message=mount_note))
                    if not steer_text.strip():
                        continue
                processed = prepare_turn_for_model(
                    steer_text,
                    workspace=self.tool_context.working_directory,
                    session_id=self._cycle_session_id,
                )
                logger.info(
                    "steer_injected display_len=%d model_len=%d",
                    len(processed.display_text),
                    len(processed.model_text),
                )
                messages.append(
                    Message.user(
                        processed.model_text, origin=MessageOrigin.REAL_USER
                    )
                )
                self.working_set.observe_references(processed.references)

            # Capacity pre-request checkpoint
            # 观测 token/工具调用密度,容量预检查；改写式（删旧+塞摘要）
            await run_pre_request_checkpoint(
                self.capacity_controller,
                self.turn_counter,
                model,
                messages,
                compact_fn=self._emergency_compact,
            )
            # Capacity refresh rewrites messages in place (bridge included);
            # do not mutate system_prompt.
            # L0: prune old tool bodies at ≥50% (deterministic, no LLM).
            self._maybe_l0_prune_tool_results(
                messages, model, system_prompt=system_prompt, tools=tools
            )
            should_trigger = (
                self._compact_cooldown_rounds <= 0
                and should_compact(
                    messages,
                    self.compaction_config,
                    real_input_tokens=self.last_real_input_tokens,
                    model=model,
                    system_prompt=system_prompt,
                    tools=tools,
                )
            )
            if should_trigger:
                logger.info(
                    "compact_triggered before_count=%d cooldown=%d",
                    len(messages), self._compact_cooldown_rounds,
                )
                compact_result = await self._run_compaction(messages)
                messages[:] = compact_result.messages
                logger.info(
                    "compact_done after_count=%d bridge_attached=%s success=%s",
                    len(messages),
                    bool(compact_result.summary_prompt),
                    compact_result.success,
                )
                if compact_result.success:
                    self._compact_cooldown_rounds = 0
                    # Bridge is already the leading user message — leave
                    # system_prompt unchanged for KV prefix cache stability.
                else:
                    self._compact_cooldown_rounds = 5
                    logger.warning(
                        "compact_failed_backoff cooldown_rounds=5 — "
                        "auto-compaction will be skipped for 5 rounds"
                    )
            elif self._compact_cooldown_rounds > 0:
                self._compact_cooldown_rounds -= 1
            # Long-session drift reminder — after compaction so a rewrite
            # doesn't immediately archive a freshly injected copy.
            self._maybe_inject_long_session_reminder(
                messages, model, system_prompt=system_prompt, tools=tools
            )

            # Flush any diagnostics queued by post-edit hooks from the
            # previous round-trip so the model sees them on this request.
            self._flush_pending_lsp_diagnostics(messages)
            # tool_choice is resolved in turn_loop (auto by default; bare
            # string "required" only when config.strict_tool_mode is set).
            request = MessageRequest(
                model=model,
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                max_tokens=max_tokens,
                temperature=self.default_temperature,
                top_p=self.default_top_p,
                reasoning_effort=reasoning_effort or self.default_reasoning_effort,
                extra_body=dict(self.default_extra_body),
            )
            logger.info(
                "llm_invoke_start round=%d msg_count=%d tools_count=%d model=%s",
                round_idx,
                len(messages),
                len(tools),
                model,
            )
            self._log_prefix_break(round_idx, system_prompt, messages, tools)
            from deepseek_tui.engine.usage_ledger import usage_source

            with usage_source("agent_round"):
                # 跑一轮 LLM 流式调用，result(TurnResult) 含本轮产出与状态：
                # assistant_message=回复 / tool_calls=待调工具(空=结束) / usage=token用量
                # cancelled=是否取消 / outcome=成功或失败类型 / error_message=错误描述
                result = await self.turn_loop.run(
                    request,
                    self.handle.emit,
                    self.handle.cancel_event,
                    tools=tools,
                    latency_turn_id=latency_turn_id,
                    round_idx=round_idx,
                )
            # Refresh the real pressure signal *within* the turn, not just at
            # turn end: every round's StreamDone carries the provider's
            # input_tokens and messages only grow between rounds, so this is
            # monotonic. Otherwise the /context panel and the pre-request
            # compaction checks (should_compact / L0) stay blind to
            # mid-turn growth until the whole turn completes.
            round_usage = result.usage
            goal_budget_blocked = False
            if round_usage is not None and round_usage.output_tokens:
                goal_before_usage = self.goal_service.snapshot()
                if (
                    goal_before_usage is not None
                    and goal_before_usage.status.value == "active"
                ):
                    self._goal_accounted_output_tokens += round_usage.output_tokens
                    goal_budget_blocked = (
                        self.goal_service.account_tokens(round_usage.output_tokens)
                        is not None
                    )
            if round_usage is not None and round_usage.total_input_tokens:
                self.last_real_input_tokens = round_usage.total_input_tokens
                # Prefix-cache baseline, per round. Anything that perturbs the
                # stable system prefix mid-turn shows up here as a sudden ratio
                # drop. Both counters zero means the provider reported nothing
                # — that is unknown, not a miss (base.md), so stay quiet.
                cache_hit = round_usage.cache_read_input_tokens
                cache_miss = round_usage.cache_creation_input_tokens
                if cache_hit or cache_miss:
                    logger.info(
                        "prefix_cache round=%d hit=%d miss=%d ratio=%.3f",
                        round_idx,
                        cache_hit,
                        cache_miss,
                        cache_hit / (cache_hit + cache_miss),
                    )
            if not result.cancelled:
                from deepseek_tui.server.agent_segments import assistant_thinking_text

                await self.handle.emit(
                    AgentRoundCompleteEvent(
                        round_idx=round_idx,
                        tool_calls=tuple(result.tool_calls or ()),
                        preface_text=_assistant_preface_text(result.assistant_message),
                        round_thinking=assistant_thinking_text(result.assistant_message),
                    )
                )
            if round_trace is not None:
                round_trace.tool_calls = len(result.tool_calls or [])
            if result.cancelled:
                from dataclasses import replace

                return replace(result, tool_round_count=tool_round_count)
            if result.assistant_message is not None:
                messages.append(result.assistant_message)
            if goal_budget_blocked:
                from dataclasses import replace

                return replace(
                    result,
                    tool_calls=[],
                    tool_round_count=tool_round_count,
                )
            if not result.tool_calls:
                if await self._handle_subagent_turn_handoff(messages):
                    continue
                # Same gate for background shells the timeout re-homed: the
                # model is still owed that result, so hand it off rather than
                # ending the turn (and tearing down the op-loop consumer)
                # while the process is mid-flight.
                if await self._handle_shell_process_turn_handoff(messages):
                    continue
                # Steer text queued after this round's drain — the usual case
                # is the user typing while the final answer streams. Steers are
                # only read at the top of a round, so ending the turn here
                # strands it: the UI has already persisted it as a delivered
                # user message that the model never reads. Loop once more and
                # let the top-of-round drain pick it up. A steer the drain
                # discards (blank text) empties the queue, so this cannot spin.
                if self.handle.has_pending_steers():
                    logger.info("turn_end_deferred_pending_steer")
                    continue
                # Checklist turn-end gate: if the model is about to stop with
                # open checklist items, inject a reminder that makes it face
                # each one. Re-fires while the model keeps making progress, so
                # a genuine "I'm done / won't do the rest" costs one extra
                # round instead of looping.
                gate_summary = self._next_checklist_gate_summary(
                    fired=checklist_gate_fires,
                    last_open=checklist_gate_last_open,
                )
                if gate_summary is not None:
                    checklist_gate_fires += 1
                    checklist_gate_last_open = gate_summary
                    from deepseek_tui.engine import reminders
                    from deepseek_tui.engine.prompts import (
                        CHECKLIST_GATE_REMINDER,
                    )

                    messages.append(
                        reminders.reminder_message(
                            reminders.CHECKLIST_INCOMPLETE_GATE,
                            CHECKLIST_GATE_REMINDER.format(
                                open_summary=gate_summary
                            ),
                        )
                    )
                    logger.info(
                        "checklist_gate_fired fire=%d open=%s",
                        checklist_gate_fires,
                        gate_summary[:200],
                    )
                    continue
                # turn_end (Claude "Stop") hooks: a blocking decision keeps
                # the loop running with the hook's reason injected as
                # context, so "don't stop until done" policies work.
                if (
                    stop_hook_fires >= _STOP_HOOK_MAX_FIRES
                    and self.hook_executor.has_hooks_for_event("turn_end")
                ):
                    logger.warning(
                        "turn_end_hook_gate_exhausted fires=%d — ending the turn",
                        stop_hook_fires,
                    )
                elif self.hook_executor.has_hooks_for_event("turn_end"):
                    stop_ctx = self._lifecycle_hook_context(model=model)
                    stop_ctx.stop_hook_active = stop_hook_active
                    stop_results = await self._run_lifecycle_hook(
                        "turn_end", stop_ctx
                    )
                    from deepseek_tui.integrations.hooks import (
                        aggregate_hook_decision,
                    )

                    stop_decision = aggregate_hook_decision(stop_results)
                    if stop_decision.blocked:
                        stop_hook_active = True
                        stop_hook_fires += 1
                        reason = (
                            stop_decision.reason
                            or "A Stop hook blocked ending the turn."
                        )
                        from deepseek_tui.engine import reminders

                        messages.append(
                            reminders.reminder_message(
                                reminders.STOP_HOOK_BLOCK,
                                f"A Stop hook prevented ending the turn: {reason}",
                            )
                        )
                        logger.info(
                            "turn_end_blocked_by_hook reason=%s",
                            reason[:200],
                        )
                        continue
                from dataclasses import replace

                return replace(result, tool_round_count=tool_round_count)

            tool_round_count += 1

            messages.append(self._build_tool_use_message(result.tool_calls))
            from deepseek_tui.server.metrics import now_ms as latency_now_ms

            tool_exec_start = latency_now_ms()
            tool_results = await self._execute_tool_calls(result.tool_calls, model)
            if round_trace is not None:
                round_trace.tool_exec_ms = latency_now_ms() - tool_exec_start
            tool_errors = sum(1 for m in tool_results if any(
                getattr(b, "is_error", False) for b in m.content if hasattr(b, "is_error")
            ))
            messages.extend(tool_results)

            # Capacity post-tool checkpoint
            # 观测 token/工具调用密度,容量后检查
            await run_post_tool_checkpoint(
                self.capacity_controller, self.turn_counter, model, messages,
            )

            # Optional durable transcript hook (Task true-resume).
            on_ckpt = self.tool_context.metadata.get("on_turn_checkpoint")
            if callable(on_ckpt):
                try:
                    maybe = on_ckpt(list(messages), tool_round_count)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except Exception:  # noqa: BLE001 — never break the turn
                    logger.debug("on_turn_checkpoint_failed", exc_info=True)

            # Capacity error escalation
            if tool_errors > 0:
                step_error_count += tool_errors
                consecutive_tool_error_steps += 1
                await run_error_escalation_checkpoint(
                    self.capacity_controller,
                    self.turn_counter,
                    model,
                    messages,
                    step_error_count=step_error_count,
                    consecutive_tool_error_steps=consecutive_tool_error_steps,
                )
            else:
                consecutive_tool_error_steps = 0

            # Stop only when exit_plan_mode left without implementing.
            # Accept paths must continue so the model can start the work.
            if tool_errors == 0 and getattr(self, "_stop_after_exit_plan", False):
                self._stop_after_exit_plan = False
                if any(tc.name == "exit_plan_mode" for tc in result.tool_calls):
                    logger.info("plan_exit_leave_stop mode=%s", self.mode)
                    from dataclasses import replace

                    return replace(result, tool_round_count=tool_round_count)

        logger.warning(
            "round_trip_limit_exceeded limit=%d", self.max_tool_round_trips
        )
        await self.handle.emit(
            ErrorEvent(
                message="Tool round-trip limit exceeded",
                retryable=False,
            )
        )
        return TurnResult(assistant_message=None, usage=None, tool_calls=[])
