"""Engine core — construction, turn loop, and conversation orchestration.

Tool dispatch, maintenance, and lifecycle/LSP methods live in sibling mixins.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
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
    is_mcp_tool,
    should_force_update_plan_first,
    should_stop_after_plan_tool,
)
from deepseek_tui.engine.events import (
    AgentRoundCompleteEvent,
    ErrorEvent,
    PluginMountEvent,
    SessionEndedEvent,
    SessionStartedEvent,
    StatusEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)
from deepseek_tui.engine.handle import (
    ApprovalHandler,
    AutoApprovalHandler,
    CancelRequestOp,
    EngineHandle,
    SendMessageOp,
)
from deepseek_tui.engine.orchestrator.helpers import (
    FOCUS_READ_BASE,
    FOCUS_WRITE_BASE,
    _assistant_preface_text,
    _detect_focus_mcp,
    _detect_focus_skill,
    _detect_locale,
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
    profile_includes_tool_search,
)
from deepseek_tui.engine.seam import SeamConfig, SeamManager
from deepseek_tui.engine.tools import (
    active_tools_for_step,
    apply_mcp_tool_deferral,
    apply_native_tool_deferral,
    build_model_tool_catalog,
    ensure_advanced_tooling,
    initial_active_tools,
)
from deepseek_tui.engine.turn import TurnLoop, TurnResult, prepare_turn_for_model
from deepseek_tui.integrations.lsp import DiagnosticBlock
from deepseek_tui.policy.approval import ApprovalCache, ExecPolicyEngine
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.tools.registry import ToolContext, ToolRegistry
from deepseek_tui.tools.subagent import SubAgentCompletion
from deepseek_tui.utils import bind_turn

if TYPE_CHECKING:
    from deepseek_tui.tools.runtime import ToolRuntime

logger = logging.getLogger(__name__)


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
        max_tool_round_trips: int = 100,
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
        self.compaction_config = compaction_config or CompactionConfig()
        self.capacity_controller = CapacityController(config=CapacityControllerConfig())
        self.session_messages: list[Message] = []
        # Compaction summary carried across turns. Without this the
        # <archived_context> summary only lived in _run_conversation's
        # local system_prompt and was lost on the next turn — compaction
        # silently became "delete history".
        self._compaction_summary_prompt: str | None = None
        self.turn_loop = TurnLoop(client, compact_fn=self._emergency_compact)
        # Deferred tools activated during the session (tool_search hits or
        # direct calls). Merged into every round's active set so an
        # activation survives past the round that produced it.
        self._activated_tool_names: set[str] = set()
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
        # Stage 3.next.1 approval cache — fingerprints repeat tool calls
        # so an APPROVED_SESSION grant doesn't have to re-prompt.
        self.approval_cache = ApprovalCache()
        # Skills integration — renders available skills into system prompt
        self.skill_registry = skill_registry
        # Skill 聚焦模式：per-turn 工具白名单。None = 全量（默认）；置位时
        # ``_get_tools_with_mcp`` 只返回交集。由 ``_handle_send_message_inner``
        # 在 try/finally 中设置与复位，不跨 turn 保留。
        self._focus_tool_whitelist: frozenset[str] | None = None
        # 插件挂载（@plugin:name）：会话级持续态，与单轮聚焦不同不在 turn 末
        # 复位。挂载后每轮开头把它折算进 ``_focus_tool_whitelist`` —— 模型只
        # 看到「只读底座 + 按插件 permissions 的写工具 + 该插件的 skill/MCP
        # 工具」。用户显式打 `/skill` 或 `@mcp` 时该轮让位（前缀优先）。
        self._active_plugin: object | None = None
        # Plugin-contributed prompt commands and agent personas, populated in
        # ``Engine.create`` from plugin contributions. Commands map their
        # ``<plugin>:<stem>`` invocation (lowercased) → PluginCommand and are
        # expanded into the user message in ``_handle_send_message_inner``.
        # Agents map ``<name>`` (lowercased) → PluginAgent and are exposed to
        # ``agent_spawn`` via ``tool_context.metadata['plugin_agents']``.
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
        # Expose the merged skill registry (workspace + plugin skills) so the
        # ``load_skill`` tool can resolve plugin skills by name. Without this,
        # load_skill re-discovers via discover_in_workspace which does not
        # merge plugin contributions, so plugin skills would be unreachable
        # by name even though they are listed in the system prompt.
        if skill_registry is not None:
            self.tool_context.metadata["skill_registry"] = skill_registry
        # Cycle / seam managers — instantiated but disabled by default. The
        # full archive-and-replan logic lives in cycle_manager.py /
        # seam_manager.py; ``Engine`` keeps surface integration minimal:
        # ``_maybe_advance_cycle`` runs at the start of each conversation
        # and only fires when the user opts in via ``Config.cycle_enabled``.
        # See HANDOVER pre-realapi-batch-2 entry for the deferred deep work.
        self.cycle_config = CycleConfig(enabled=False)
        self.seam_manager: SeamManager | None = None
        self._cycle_session_id: str = ""
        self._cycle_n: int = 0
        self._cycle_started_at: int = 0
        # Working-set tracker — observes user messages and tool calls to
        # surface relevant file paths for compaction pinning + system-prompt
        # injection. One per
        # Engine instance: workspace lives on tool_context.working_directory.
        self.working_set = WorkingSet(workspace=self.tool_context.working_directory)
        self._mcp_tools_cache: list[dict[str, Any]] | None = None
        self.tool_profile: str | None = None
        # Issue #756: parent turn resumes when direct children complete.
        self._subagent_completions: asyncio.Queue[SubAgentCompletion] = (
            asyncio.Queue(maxsize=64)
        )
        self._consumed_subagent_completions: set[str] = set()
        self._activity_coordinator = SessionActivityCoordinator(
            self, self.handle.try_emit
        )

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

    def _mcp_focus_whitelist(self, server: str) -> frozenset[str]:
        """聚焦某个 MCP 连接器时的工具白名单：该 server 的工具 + 基座。

        基座为只读探索 + 写工具（``FOCUS_READ_BASE | FOCUS_WRITE_BASE``）：
        连接器聚焦不仅查询连接器，还要能对工作区文件动手（如根据 PR
        改代码），所以写工具一并放行。Exec/网络等领域工具不进基座。
        """
        return frozenset(
            self._server_tool_names(server) | FOCUS_READ_BASE | FOCUS_WRITE_BASE
        )

    def set_active_plugin(self, name: str | None) -> str:
        """挂载 / 摘除会话级插件。``name=None`` 或 ``"off"`` → 摘除。

        按名在已发现插件里大小写不敏感查找并存入 ``self._active_plugin``；
        返回一条给用户看的结果说明。未找到时保持原状并回错。
        """
        if name is None or name.lower() == "off":
            self._active_plugin = None
            return "已摘除插件，恢复全量工具与技能。"
        from deepseek_tui.integrations.plugins import discover_plugins

        ws = self.tool_context.working_directory
        try:
            plugins = discover_plugins(workspace=ws)
        except Exception:  # noqa: BLE001 — 发现失败不该炸会话
            logger.warning("plugin discovery failed for mount", exc_info=True)
            plugins = []
        match = next(
            (p for p in plugins if p.manifest.name.lower() == name.lower()), None
        )
        if match is None:
            return f"未找到插件：{name}（用 plugin list 查看已安装）。"
        self._active_plugin = match
        m = match.manifest
        note = f"已应用插件 {m.name}，本会话仅用其工具 + 基础工具。"
        # trusted 才收 MCP（collect_contributions 语义）；未信任时提示。
        if m.mcp_servers and not getattr(match, "trusted", False):
            note += " 注意：该插件的 MCP 未激活，需先信任该插件。"
        return note

    def _active_plugin_skills(self) -> list[object]:
        """当前挂载插件贡献的 skill 集（用于收窄 system prompt 注入）。"""
        if self._active_plugin is None:
            return []
        from deepseek_tui.integrations.plugins import collect_contributions

        try:
            return list(collect_contributions([self._active_plugin]).skills)
        except Exception:  # noqa: BLE001
            logger.warning("collect plugin skills failed", exc_info=True)
            return []

    def _active_plugin_whitelist(self) -> frozenset[str] | None:
        """当前挂载插件的每轮工具白名单（收窄语义）。

        只读探索基座（``FOCUS_READ_BASE``）始终放行；按插件 permissions
        决定是否加写工具（``FOCUS_WRITE_BASE``）；再加插件 skill 声明的
        allowed-tools + 插件自带 MCP server 的全部工具。None = 未挂载。
        Exec/网络等领域工具不进基座，需插件 skill 显式 allowed-tools 声明。
        """
        plugin = self._active_plugin
        if plugin is None:
            return None
        from deepseek_tui.integrations.plugins import (
            capability_values_from_permissions,
            collect_contributions,
        )

        allowed: set[str] = set(FOCUS_READ_BASE)
        caps = capability_values_from_permissions(plugin.manifest.permissions)
        if "writes_files" in caps:
            allowed |= set(FOCUS_WRITE_BASE)
        try:
            contribs = collect_contributions([plugin])
        except Exception:  # noqa: BLE001
            logger.warning("collect plugin contributions failed", exc_info=True)
            contribs = None
        if contribs is not None:
            for skill in contribs.skills:
                declared = getattr(skill, "allowed_tools", None)
                if declared:
                    allowed |= set(declared)
            # Defense in depth: collect_contributions already skips MCP
            # servers for untrusted plugins (and Engine.create never started
            # the server, so _server_tool_names would be empty anyway). Gate
            # explicitly here too so the whitelist invariant - "untrusted ->
            # no MCP tool names" - holds even if contribution collection is
            # later refactored to collect servers eagerly.
            if plugin.trusted:
                for server in contribs.mcp_servers:
                    allowed |= self._server_tool_names(server.name)
        return frozenset(allowed)

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
        return render_plugin_context(
            name=plugin.name,
            version=plugin.manifest.version,
            path=str(plugin.path.expanduser().resolve()),
            permissions=plugin.manifest.permissions,
            trusted=plugin.trusted,
            mcp_active=has_mcp and plugin.trusted,
            has_mcp=has_mcp,
        )

    def _render_plugin_components_context(self) -> str | None:
        """Render the ``## Plugin Commands & Agents`` block, or ``None``.

        Lists plugin-contributed slash commands and agent personas so the
        model knows they exist. Suppressed while a plugin is mounted (the
        mount already narrows the surface to one plugin) to avoid noise.
        """
        if self._active_plugin is not None:
            return None
        if not self.plugin_commands and not self.plugin_agents:
            return None
        from deepseek_tui.engine.prompts import render_plugin_components_context

        block = render_plugin_components_context(
            list(self.plugin_commands.values()),
            list(self.plugin_agents.values()),
        )
        return block or None

    def _render_plugin_rules_context(self) -> str | None:
        """Render plugin ``rules`` as a system-prompt block.

        CodeBuddy plugins carry their core behavior in ``rules`` marked
        ``alwaysApply: true``. Mounted (``@plugin:name``): the mounted
        plugin's rule bodies are injected verbatim — that IS the plugin's
        behavior the user opted into. Unmounted: rules collapse to one
        summary line each with a mount hint (full bodies from every
        installed plugin would bloat and dilute the prompt).
        """
        if not self.plugin_rules:
            return None
        from deepseek_tui.engine.prompts import render_plugin_rules_context

        active = self._active_plugin.name if self._active_plugin else None
        block = render_plugin_rules_context(
            self.plugin_rules, active_plugin=active
        )
        return block or None

    def _advanced_tool_flags(self) -> tuple[bool, bool]:
        """Whether ``tool_search`` / ``code_execution`` are included this turn.

        ``ensure_advanced_tooling`` re-adds these two meta-tools to the catalog
        AFTER the focus whitelist filter, so without gating them here they
        would bypass the whitelist and break the plugin mount's confinement
        (e.g. a ``permissions: ["read"]`` plugin would still leave
        ``code_execution`` - arbitrary Python incl. ``subprocess`` - callable).

        When a focus whitelist is active (plugin mount / skill / mcp focus),
        the meta-tools are included ONLY if the whitelist explicitly lists
        them (e.g. a plugin skill declared them via ``allowed-tools``).
        Otherwise the normal profile-based defaults apply.
        """
        wl = self._focus_tool_whitelist
        if wl is None:
            return (
                profile_includes_tool_search(self.tool_profile),
                self.tool_profile is None,
            )
        from deepseek_tui.engine.tools import (
            CODE_EXECUTION_TOOL_NAME,
            TOOL_SEARCH_BM25_NAME,
            TOOL_SEARCH_REGEX_NAME,
        )

        include_search = bool({TOOL_SEARCH_BM25_NAME, TOOL_SEARCH_REGEX_NAME} & wl)
        include_code = CODE_EXECUTION_TOOL_NAME in wl
        return include_search, include_code

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
        if mcp is None:
            result = filter_tools_for_profile(list(native_tools), profile)
        else:
            mcp_tools = self._mcp_tools_cache
            if mcp_tools is None:
                mcp_tools = mcp.cached_tools()
            if mcp_tools is None:
                # Never block a user turn on cold MCP subprocess startup.
                mcp.schedule_background_discover()
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

        # 聚焦模式：收窄到最小工具白名单。在 catalog 层直接裁剪（而非依赖
        # defer_loading），确保模型无法经 tool-search 调回被屏蔽的工具。
        if self._focus_tool_whitelist is not None:
            whitelist = self._focus_tool_whitelist
            result = [
                t
                for t in result
                if (t.get("function", t) or {}).get("name") in whitelist
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
        max_tool_round_trips: int = 100,
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
        # Discover installed plugins and fan their components out to the
        # existing subsystems: skills → SkillRegistry, hooks →
        # HookExecutor, MCP servers → McpManager (via create_tool_runtime).
        plugin_contribs = None
        if cfg.features.plugins:
            from deepseek_tui.integrations.plugins import (
                collect_contributions,
                discover_plugins,
            )

            loaded_plugins: list[Any] = []
            try:
                loaded_plugins = discover_plugins(workspace=ws)
                plugin_contribs = collect_contributions(loaded_plugins)
            except Exception:  # noqa: BLE001 — a malformed plugin must not
                # crash engine construction; degrade to no plugin contributions.
                logger.warning("plugin discovery failed", exc_info=True)
            if plugin_contribs is not None:
                for warning in plugin_contribs.warnings:
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
        if plugin_contribs is not None and plugin_contribs.skills:
            from deepseek_tui.integrations.plugins import merge_plugin_skills

            merge_plugin_skills(skill_reg, plugin_contribs)
        # Pull sampling / reasoning defaults out of Config so the per-turn
        # MessageRequest carries them all the way to DeepSeekClient.
        provider_cfg = cfg.effective_provider_config()
        # When reusing a shared runtime, create a per-engine ToolContext with
        # the correct working_directory so system prompts reflect the thread's
        # workspace rather than the process cwd. We branch off the runtime's
        # context instead of constructing a bare one, otherwise the per-engine
        # context loses task_manager/subagent_manager/network_policy/policy and
        # registered-but-runtime-unwired tools (e.g. task_shell_start) become
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
        if isinstance(tool_runtime, ToolRuntime):
            from deepseek_tui.tools.runtime import build_subagent_manager

            per_engine_subagent_manager, _ = build_subagent_manager(cfg, ws)
            per_engine_context = _dc.replace(
                runtime.context,
                working_directory=ws,
                subagent_manager=per_engine_subagent_manager,
                metadata=dict(runtime.context.metadata),
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
        from deepseek_tui.client.base import MeteredLLMClient

        if isinstance(client, MeteredLLMClient):
            engine.turn_usage_ledger = client._ledger
        else:
            engine.client = MeteredLLMClient(client, engine.turn_usage_ledger)
        engine.turn_loop = TurnLoop(engine.client, compact_fn=engine._emergency_compact)
        if isinstance(tool_runtime, ToolRuntime):
            engine._owns_tool_runtime = False
        # Register plugin prompt commands + agent personas so slash commands
        # expand into messages and agent_spawn can resolve persona names.
        if plugin_contribs is not None:
            engine.plugin_commands = {
                c.qualified.lower(): c for c in plugin_contribs.commands
            }
            engine.plugin_agents = {
                a.name.lower(): a for a in plugin_contribs.agents
            }
            if engine.plugin_agents:
                engine.tool_context.metadata["plugin_agents"] = engine.plugin_agents
            engine.plugin_rules = [
                r for r in plugin_contribs.rules if r.always_apply
            ]
            engine.plugin_skill_names = {s.name for s in plugin_contribs.skills}
            engine.plugin_summary = {
                "plugins": len(loaded_plugins),
                "skills": len(plugin_contribs.skills),
                "commands": len(plugin_contribs.commands),
                "agents": len(plugin_contribs.agents),
                "rules": len(plugin_contribs.rules),
                "hooks": len(plugin_contribs.hook_entries),
                "mcp": len(plugin_contribs.mcp_servers),
            }
            engine.plugin_names = [p.name for p in loaded_plugins]
        engine.capacity_controller = CapacityController(
            config=CapacityControllerConfig.from_app_config(cfg.capacity)
        )
        # Cycle / Seam wiring (off by default). Honors ``Config.cycle_enabled``
        # and ``Config.seam_enabled`` once those fields exist; today they
        # default to False so behavior is unchanged from the pre-batch state.
        engine.cycle_config = CycleConfig(
            enabled=bool(getattr(cfg, "cycle_enabled", False)),
        )
        if bool(getattr(cfg, "seam_enabled", False)):
            engine.seam_manager = SeamManager(
                flash_client=engine.client, config=SeamConfig(enabled=True)
            )
        engine._cycle_session_id = uuid.uuid4().hex
        engine._cycle_started_at = int(time.time())
        engine.mode = mode
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

    def context_breakdown(self, model: str | None = None) -> dict[str, int]:
        """Estimate token occupancy by category for the next request.

        Returns ``{bucket_name: tokens, ..., "total": int, "window": int}``.
        Buckets:

        - ``system_prompt`` — base system prompt body
        - ``tools`` — legacy combined JSON schema bucket
        - ``tool_definitions`` — initially active built-in tool schemas
        - ``mcp`` — initially active MCP tool schemas
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
            working_set_summary=self.working_set.summary() or None,
            api_tools=api_tools,
            workspace=self.tool_context.working_directory,
            mode=(self.mode or "agent").strip() or "agent",
            real_input_tokens=self.last_real_input_tokens,
        )

    async def context_breakdown_live(self, model: str | None = None) -> dict[str, int]:
        """Estimate context using the same tool catalog sent to the model.

        Unlike :meth:`context_breakdown`, this async path considers dynamically
        discovered MCP tools, then applies TurnLoop's initial active filter.

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
            working_set_summary=self.working_set.summary() or None,
            api_tools=api_tools,
            workspace=self.tool_context.working_directory,
            mode=(self.mode or "agent").strip() or "agent",
            real_input_tokens=self.last_real_input_tokens,
        )

    def _initial_request_tools_for_context(
        self, api_tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Initial active-tool filtering for context counts.

        Replays the same ordering the streaming turn uses so the breakdown
        counts only the tools sent on the first request: apply native/MCP
        deferral, append the always-active advanced tools, then keep the
        initially active set. Deferral is idempotent, so this is safe whether
        the caller passes a raw registry catalog (``context_breakdown``) or a
        catalog that already went through ``build_model_tool_catalog``
        (``context_breakdown_live``).
        """
        tools = [dict(tool) for tool in api_tools]
        for tool in tools:
            function = tool.get("function")
            if isinstance(function, dict):
                tool["function"] = dict(function)
        if not tools:
            return []

        def _name(tool: dict[str, Any]) -> str:
            function = tool.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                return function["name"]
            return ""

        mode = (self.mode or "agent").strip() or "agent"
        native = [t for t in tools if not is_mcp_tool(_name(t))]
        mcp = [t for t in tools if is_mcp_tool(_name(t))]
        apply_native_tool_deferral(native, mode)
        apply_mcp_tool_deferral(mcp, mode)
        catalog = native + mcp

        _include_search, _include_code = self._advanced_tool_flags()
        ensure_advanced_tooling(
            catalog,
            include_tool_search=_include_search,
            include_code_execution=_include_code,
        )
        active_names = initial_active_tools(catalog)
        return active_tools_for_step(catalog, active_names, force_update_plan_first=False)

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
            finally:
                self.handle._mark_turn_idle()

    def _expand_plugin_command(self, content: str) -> str | None:
        """Expand a ``/<plugin>:<command> [args]`` invocation, else ``None``.

        Matches a leading slash token that contains a ``:`` namespace (so it
        never collides with built-in ``/skill-name`` focus, which has no
        colon). Substitutes ``$ARGUMENTS`` / ``${ARGUMENTS}`` in the command
        body with the trailing arguments; appends any args when the template
        declares no placeholder.
        """
        if not self.plugin_commands:
            return None
        text = (content or "").strip()
        if not text.startswith("/") or ":" not in text.split(maxsplit=1)[0]:
            return None
        parts = text[1:].split(maxsplit=1)
        token = parts[0]
        args = parts[1] if len(parts) > 1 else ""
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
        把用户消息拼进会话历史并按模式(plan/workflow/中文)追加临时 hint,
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

        user_message = Message.user(processed.model_text)

        prior_count = len(self.session_messages)
        working_messages = [*self.session_messages, user_message]
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
            working_messages.append(
                Message.user(
                    "[System] Before creating the plan, explore the repository "
                    "structure and relevant code first to ground your plan in "
                    "the actual codebase."
                )
            )

        mode_hint = ""
        if self.mode == "workflow":
            mode_hint = (
                "\n\n[Turn hint] Use the workflow tool to decompose "
                "the user's request into a phased workflow spec."
            )

        # Language enforcement: inject a turn-level hint when user
        # speaks Chinese so the model doesn't drift into English.
        detected_locale = _detect_locale(processed.display_text or "")
        if detected_locale == "zh":
            working_messages.append(
                Message.user(
                    "**Important**: The user asked the question in Chinese. Your thought process (reasoning_content) and final reply must be entirely in Simplified Chinese."
                    "Technical identifiers such as code, paths, and commands should remain unchanged; only the natural language portion should use Chinese."
                )
            )

        try:
            # 聚焦模式：置位 per-turn 工具白名单，``_get_tools_with_mcp`` 据此
            # 收窄 catalog。在 finally 中复位，异常/取消也不会泄漏到下一 turn。
            # skill 声明 ``allowed-tools`` 则完全覆盖固定白名单；否则回退到
            # ``FOCUS_READ_BASE | FOCUS_WRITE_BASE``（技能引导任务，需完整读写；
            # exec/领域工具由 skill 用 allowed-tools 显式 opt-in）。
            # MCP 连接器聚焦：该 server 工具 + 读基座 + 写基座。
            # 显式前缀（/skill、@mcp）优先级最高；两者都未命中且挂载了插件时，
            # 回退到插件白名单（持续态）。都无 -> 全量（None）。
            if focus_skill is not None:
                declared = getattr(focus_skill, "allowed_tools", None)
                self._focus_tool_whitelist = (
                    frozenset(declared)
                    if declared
                    else (FOCUS_READ_BASE | FOCUS_WRITE_BASE)
                )
            elif focus_mcp is not None:
                self._focus_tool_whitelist = self._mcp_focus_whitelist(focus_mcp)
            elif self._active_plugin is not None:
                self._focus_tool_whitelist = self._active_plugin_whitelist()
                # Read-only放行插件自身目录（工作区外），让模型能 read_file/
                # list_dir/grep 插件的 skill/清单等资源；写工具仍锁工作区。
                # 将来 skills 的 companion-file 根可在此 append。
                self.tool_context.extra_read_roots = (
                    self._active_plugin.path.expanduser().resolve(),
                )
            else:
                self._focus_tool_whitelist = None
            await self.handle.emit(
                TurnStartedEvent(user_text="" if op.hidden else processed.display_text)
            )
            self.turn_usage_ledger.reset()
            self._save_crash_checkpoint(
                working_messages,
                model=op.model or self.default_model,
            )
            sys_prompt = build_system_prompt(
                op.system_prompt,
                mode=_resolve_app_mode(self.mode),
                skills_context=self._render_skills_context(
                    only=focus_skill
                    if focus_skill is not None
                    else (
                        self._active_plugin_skills()
                        if focus_mcp is None and self._active_plugin is not None
                        else None
                    )
                ),
                plugin_context=(
                    self._render_plugin_context()
                    if focus_mcp is None and self._active_plugin is not None
                    else None
                ),
                plugin_components_context=self._render_plugin_components_context(),
                plugin_rules_context=self._render_plugin_rules_context(),
                working_set_summary=self.working_set.summary() or None,
                workspace=self.tool_context.working_directory,
                locale_tag=_detect_locale(processed.display_text or ""),
                workflow_guidelines=self.tool_registry.contains("workflow"),
            )
            if mode_hint:
                sys_prompt += mode_hint
            if self._compaction_summary_prompt:
                # Re-inject archived-context summaries from earlier
                # compactions; build_system_prompt regenerates from scratch
                # every turn and would otherwise drop them.
                sys_prompt = f"{sys_prompt}\n\n{self._compaction_summary_prompt}"
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
                # before the cancel landed, result.usage.input_tokens is a
                # valid pressure reading — more accurate than the char-based
                # estimate. Record it so the next turn's should_compact /
                # seam / cycle decisions aren't forced back to the ~6x-
                # undercounting estimate. If no usage arrived (cancel too
                # early), keep the previous value rather than zeroing — a
                # stale-but-real reading beats falling back to the estimate.
                cancelled_usage = result.usage
                if (
                    cancelled_usage is not None
                    and getattr(cancelled_usage, "input_tokens", 0)
                ):
                    self.last_real_input_tokens = cancelled_usage.input_tokens
                await self.handle.emit(
                    TurnCancelledEvent(
                        reason=self.handle.cancel_reason or "user_cancelled"
                    )
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
                if op.hidden:
                    self.session_messages = [
                        *self.session_messages,
                        *working_messages[prior_count + 1 :],
                    ]
                else:
                    self.session_messages = working_messages
            if not result.cancelled:
                from deepseek_tui.state.session import clear_checkpoint

                clear_checkpoint()
            usage = result.usage
            # Record the last real input_tokens from the provider so the
            # next turn's should_compact has a zero-estimation-error signal.
            # result.usage is the final round's StreamDone usage, which is the
            # largest input of the turn (messages only grow between rounds).
            if usage is not None and getattr(usage, "input_tokens", 0):
                self.last_real_input_tokens = usage.input_tokens
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
            if not result.cancelled:
                self._user_turn_index += 1
        finally:
            self.handle.clear_response_id()
            # 复位聚焦模式白名单，确保不跨 turn 保留。
            self._focus_tool_whitelist = None
            # 同理复位只读放行根：仅在挂载插件的 turn 内有效，取消/异常也不泄漏。
            self.tool_context.extra_read_roots = ()

    def _enqueue_subagent_completion(self, completion: SubAgentCompletion) -> None:
        """Thread-safe enqueue from sub-agent driver tasks (#756)."""
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

    def _mark_subagent_tool_result_consumed(
        self, tool_name: str, metadata: dict[str, Any] | None
    ) -> None:
        """Mark sub-agent completions already returned by wait/result tools."""
        if not isinstance(metadata, dict):
            return

        if tool_name == "resume_agent":
            agent_id = metadata.get("agent_id")
            if isinstance(agent_id, str):
                self._consumed_subagent_completions.discard(agent_id)
            return

        if tool_name not in {
            "agent_wait",
            "agent_result",
            "delegate_to_agent",
            "agent_cancel",
            "close_agent",
        }:
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

    async def _handle_subagent_turn_handoff(self, messages: list[Message]) -> bool:
        """Wait for direct children and inject ``<deepseek:subagent.done>`` (#756).

        Returns True when completions were injected and the turn should continue.
        """
        mgr = self.tool_context.subagent_manager
        if mgr is None:
            return False

        completions = self._drain_subagent_completions()
        running = mgr.running_count()
        if running > 0:
            await self.handle.emit(
                StatusEvent(
                    message=f"Waiting on {running} sub-agent(s) to complete..."
                )
            )
            deadline = time.monotonic() + 600.0
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
                running = mgr.running_count()
            if timed_out:
                completions.extend(self._drain_subagent_completions())
        else:
            completions.extend(self._drain_subagent_completions())

        if not completions:
            return False

        count = len(completions)
        for item in completions:
            messages.append(Message.user(item.payload))
        await self.handle.emit(
            StatusEvent(
                message=f"Resuming turn with {count} sub-agent completion(s)"
            )
        )
        logger.info("subagent_handoff count=%d", count)
        return True

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
        # Advanced meta-tool (tool_search / code_execution) inclusion is gated
        # by the focus whitelist so a plugin mount can actually confine them.
        _turn_include_search, _turn_include_code = self._advanced_tool_flags()
        self.turn_counter += 1
        step_error_count = 0
        consecutive_tool_error_steps = 0
        # Cycle boundary check (opt-in). When the active input grows past
        # ``cycle_config.threshold_for(model)``, archive the cycle to disk
        # and continue with a trimmed message list. Best-effort — failures
        # never block the conversation.
        # 输入逼近窗口上限时，归档全量历史到磁盘、只留最近 8 条继续
        if self.cycle_config.enabled:
            await self._maybe_advance_cycle(messages, model)
        turn_id = self.tool_context.metadata.get("turn_latency_turn_id")
        from deepseek_tui.server.metrics import get_turn_latency

        latency_turn_id = str(turn_id) if turn_id else None
        tool_round_count = 0
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
                if steer_text:
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
                    messages.append(Message.user(processed.model_text))
                    self.working_set.observe_references(processed.references)

            # Capacity pre-request checkpoint
            # 观测 token/工具调用密度,容量预检查；改写式（删旧+塞摘要）
            _cap_decision, _compacted, cap_summary = await run_pre_request_checkpoint(
                self.capacity_controller,
                self.turn_counter,
                model,
                messages,
                compact_fn=self._emergency_compact,
            )
            if cap_summary:
                system_prompt = (
                    f"{system_prompt}\n\n{cap_summary}"
                    if system_prompt
                    else cap_summary
                )
            # 层级压缩；L1 = 192K、L2 = 384K、L3 = 576K
            # 发请求前,用真实 token 数判断是否越过 L1/L2/L3 阈值;若越过且该级未产出过,
            # 就用便宜的 Flash 模型把"逐字窗口之前的旧消息"(或已有接缝)压成一段浓缩摘要,
            # 插入(而非删除)到逐字窗口边界上——既省 token 又保住前缀缓存,
            # 还给 LLM 留了一座读懂历史的桥。失败则静默降级,不影响主请求。
            await self._maybe_layered_context_checkpoint(messages, model)
            hard_cap_hit = len(messages) > 500
            should_trigger = hard_cap_hit or (
                self._compact_cooldown_rounds <= 0
                and should_compact(
                    messages, self.compaction_config,
                    real_input_tokens=self.last_real_input_tokens,
                )
            )
            if should_trigger:
                logger.info(
                    "compact_triggered before_count=%d hard_cap=%s cooldown=%d",
                    len(messages), hard_cap_hit, self._compact_cooldown_rounds,
                )
                compact_result = await self._run_compaction(messages)
                messages[:] = compact_result.messages
                logger.info(
                    "compact_done after_count=%d summary_attached=%s success=%s",
                    len(messages),
                    bool(compact_result.summary_prompt),
                    compact_result.success,
                )
                if compact_result.success:
                    self._compact_cooldown_rounds = 0
                    if compact_result.summary_prompt:
                        system_prompt = f"{system_prompt}\n\n{compact_result.summary_prompt}"
                        # _run_compaction already persisted the summary via
                        # _record_compaction_summary; the local system_prompt
                        # var only lives until this turn ends.
                else:
                    # Compaction failed (e.g. summary model returned empty).
                    # Don't retry every round — it'll just fail the same way
                    # and waste 3 LLM calls per round for the whole turn.
                    # Back off for several rounds; the hard cap can still
                    # force a retry if messages pile up dangerously.
                    self._compact_cooldown_rounds = 5
                    logger.warning(
                        "compact_failed_backoff cooldown_rounds=5 — "
                        "auto-compaction will be skipped for 5 rounds"
                    )
            elif self._compact_cooldown_rounds > 0:
                self._compact_cooldown_rounds -= 1

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
                    include_tool_search=_turn_include_search,
                    include_code_execution=_turn_include_code,
                    extra_active_tools=self._activated_tool_names,
                    latency_turn_id=latency_turn_id,
                    round_idx=round_idx,
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
            if not result.tool_calls:
                if await self._handle_subagent_turn_handoff(messages):
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

            # Plan mode: stop after successful update_plan
            if tool_errors == 0 and any(
                should_stop_after_plan_tool(self.mode, tc.name, True)
                for tc in result.tool_calls
            ):
                logger.info("plan_tool_stop mode=%s", self.mode)
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
