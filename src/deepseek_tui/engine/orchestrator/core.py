"""Engine core — construction, turn loop, and conversation orchestration.

Mirrors Rust ``crates/tui/src/core/engine`` entry points. Tool dispatch,
maintenance, and lifecycle/LSP methods live in sibling mixins.
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
    FOCUS_MODE_TOOLS,
    _assistant_preface_text,
    _detect_focus_skill,
    _detect_locale,
    _resolve_app_mode,
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
        # the DeepSeek usage payload via the pricing module. Mirrors
        # Rust ``App.session_cost`` — the footer reads these to render
        # the cost chip and the ``/cost`` slash command sources from
        # the same fields.
        self.session_cost_usd: float = 0.0
        self.session_cost_cny: float = 0.0
        # 2026-05-15: cumulative cache hit/miss tokens across the whole
        # session. Intentional deviation from Rust ``footer_cache_spans``
        # (ui.rs:7377), which displays only ``last_prompt_cache_hit_tokens``
        # — i.e. the most recent turn. DeepSeek's prefix cache means
        # every turn after the first has a near-100% hit ratio, so the
        # per-turn number is constant ~99% and carries no information.
        # The session-cumulative ratio actually shows the user how much
        # prompt-bytes they have saved.
        # See HANDOVER §九 ``cache_chip.2026-05-15 cumulative``.
        self.session_cache_hit_total: int = 0
        self.session_cache_miss_total: int = 0
        # Stage 4.4 post-edit LSP diagnostics — Rust ``Engine.pending_lsp_blocks``
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
        # Per-tool snapshots for /undo (mirrors Rust pre_tool_snapshot, #384).
        # Maps tool_call_id → list[(absolute_path, original_bytes_or_None)].
        # None means file did not exist before the tool ran.
        self.tool_snapshots: dict[str, list[tuple[Path, bytes | None]]] = {}
        self._max_tool_snapshots = 5
        self._max_snapshot_file_size = 1_048_576  # 1 MB
        # Sampling / reasoning defaults — populated from Config in
        # ``Engine.create``. Without these, ``_run_conversation`` would
        # build a ``MessageRequest`` missing reasoning_effort/temperature
        # and DeepSeek-R1 / V4 thinking would never activate. Mirrors
        # Rust ``Engine`` which reads them from EngineConfig per turn.
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
        # Cycle / seam managers — instantiated but disabled by default. The
        # full Rust archive-and-replan logic lives in cycle_manager.py /
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
        # injection. Mirrors Rust ``WorkingSet`` (working_set.rs). One per
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
        """Replace in-memory chat history (Rust ``Op::SyncSession`` parity)."""
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
        hook_executor = build_lifecycle_hook_executor(cfg, ws)
        if isinstance(tool_runtime, ToolRuntime):
            runtime = tool_runtime
        else:
            mcp_flag = cfg.features.mcp if start_mcp is None else start_mcp
            runtime = await create_tool_runtime(
                config=cfg,
                working_directory=working_directory,
                mode=mode,
                task_data_dir=task_data_dir,
                start_mcp=mcp_flag,
                mcp_manager=mcp_manager,  # type: ignore[arg-type]
            )
        # Make [providers.X] context_window overrides visible to
        # context_window_for_model() even when Config was built directly
        # (server / tests) instead of through ConfigLoader.load.
        from deepseek_tui.config.providers import register_provider_context_windows

        register_provider_context_windows(cfg)
        # Discover skills for system prompt injection
        skill_reg = discover_in_workspace(workspace=working_directory)
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

        ``only`` 为聚焦模式的目标 Skill：传入时只把这一个 skill 列进
        ``## Skills`` 段（用临时单-skill registry，不改 ``self.skill_registry``）；
        为 ``None`` 时渲染全量（默认）。
        """
        if self.skill_registry is None:
            return None
        from deepseek_tui.integrations.skills import (
            SkillRegistry,
            render_available_skills_context,
        )

        registry = self.skill_registry
        if only is not None:
            registry = SkillRegistry(skills=[only])
        return render_available_skills_context(registry) or None

    def _accrue_child_token_cost_from_metadata(
        self, metadata: dict[str, Any] | None
    ) -> None:
        """Roll child-tool token usage into session cost (Rust #524 / tool_routing)."""
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
        """Mirror TurnLoop's initial active tool filtering for context counts.

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

        ensure_advanced_tooling(
            catalog,
            include_tool_search=profile_includes_tool_search(self.tool_profile),
            include_code_execution=self.tool_profile is None,
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
        processed = prepare_turn_for_model(
            op.content or "",
            workspace=self.tool_context.working_directory,
            session_id=self._cycle_session_id,
            turn_id=turn_id,
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
        focus_skill = _detect_focus_skill(
            processed.display_text or op.content or "", self.skill_registry
        )
        if focus_skill is not None:
            logger.info("skill_focus_mode skill=%s", getattr(focus_skill, "name", "?"))

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
        # and inject a grounding hint (mirrors Rust engine.rs:956)
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
            # ``FOCUS_MODE_TOOLS``。
            if focus_skill is not None:
                declared = getattr(focus_skill, "allowed_tools", None)
                self._focus_tool_whitelist = (
                    frozenset(declared) if declared else FOCUS_MODE_TOOLS
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
                skills_context=self._render_skills_context(only=focus_skill),
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
            # corrupt the context for every later turn. Mirrors the
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
            while running > 0:
                if self.handle.cancel_event.is_set():
                    return False
                if time.monotonic() > deadline:
                    logger.warning(
                        "subagent_handoff_timeout running=%d", running
                    )
                    return False
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
    ) -> TurnResult:
        """
        是单个 turn 的核心工具循环——最多跑 max_tool_round_trips+1 轮,
        每轮先做各种上下文维护(cycle 归档、drain 中途转向的 steer 消息、容量预检查、超阈值就压缩历史、刷 LSP 诊断),
        再带上工具向 LLM 发一次请求;若模型回工具调用就执行工具、把结果塞回消息列表进入下一轮,直到模型给出最终答案(或触发取消/错误上限),返回 TurnResult
        """
        tools = await self._get_tools_with_mcp()
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
            # Drain steer messages — mid-turn user input (mirrors turn_loop.rs:49-57 )
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

            # Capacity pre-request checkpoint (mirrors capacity_flow.rs:13-34)
            # 观测 token/工具调用密度,容量预检查；改写式（删旧+塞摘要）
            await run_pre_request_checkpoint(
                self.capacity_controller,
                self.turn_counter,
                model,
                messages,
                compact_fn=self._emergency_compact,
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
                reasoning_effort=self.default_reasoning_effort,
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
                    include_tool_search=profile_includes_tool_search(self.tool_profile),
                    include_code_execution=self.tool_profile is None,
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

            # Capacity post-tool checkpoint (mirrors capacity_flow.rs:37-76)
            # 观测 token/工具调用密度,容量后检查
            await run_post_tool_checkpoint(
                self.capacity_controller, self.turn_counter, model, messages,
            )

            # Capacity error escalation (mirrors capacity_flow.rs:78-151)
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

            # Plan mode: stop after successful update_plan (Rust turn_loop.rs:1634)
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
