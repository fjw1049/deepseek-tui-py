

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.capacity import CapacityController, CapacityControllerConfig
from deepseek_tui.engine.capacity import (
    run_error_escalation_checkpoint,
    run_post_tool_checkpoint,
    run_pre_request_checkpoint,
)
from deepseek_tui.engine.capacity import (
    CompactionConfig,
    CompactionResult,
    compact_messages_safe,
    should_compact,
)
from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.engine.cycle import (
    CycleConfig,
    archive_cycle,
    should_advance_cycle,
)
from deepseek_tui.engine.dispatch import (
    emit_tool_audit,
    format_tool_error,
    is_mcp_tool,
    parse_parallel_tool_calls,
    should_force_update_plan_first,
    should_parallelize_tool_batch,
    should_stop_after_plan_tool,
)
from deepseek_tui.engine.events import (
    AgentRoundCompleteEvent,
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ElevationRequiredEvent,
    ErrorEvent,
    SandboxDeniedEvent,
    SessionStartedEvent,
    StatusEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
    UserInputRequiredEvent,
    WorkflowProgressEvent,
)
from deepseek_tui.engine.handle import (
    ApprovalHandler,
    AutoApprovalHandler,
    CancelRequestOp,
    EngineHandle,
    SendMessageOp,
)
from deepseek_tui.engine.turn import prepare_turn_for_model
from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.engine.seam import SeamConfig, SeamManager
from deepseek_tui.engine.cycle import SessionActivityCoordinator
from deepseek_tui.engine.tools import (
    CODE_EXECUTION_TOOL_NAME,
    MULTI_TOOL_PARALLEL_NAME,
    REQUEST_USER_INPUT_NAME,
    active_tools_for_step,
    apply_mcp_tool_deferral,
    apply_native_tool_deferral,
    build_model_tool_catalog,
    ensure_advanced_tooling,
    execute_code_execution_tool,
    execute_tool_search,
    initial_active_tools,
    is_tool_search_tool,
    missing_tool_error_message,
)
from deepseek_tui.engine.prompts import profile_includes_tool_search
from deepseek_tui.engine.turn import TurnLoop, TurnResult
from deepseek_tui.engine.context import WorkingSet
from deepseek_tui.policy.approval import (
    ApprovalCache,
    ApprovalCacheStatus,
    build_approval_key,
)
from deepseek_tui.policy.approval import ExecPolicyEngine
from deepseek_tui.policy.approval import ApprovalDecision
from deepseek_tui.integrations.lsp import (
    LSP_MANAGER_KEY,
    DiagnosticBlock,
    LspManager,
    edited_paths_for_tool,
    render_blocks,
)
from deepseek_tui.engine.prompts import AppMode as _AppMode
from deepseek_tui.protocol.messages import Message, TextBlock, ToolUseBlock
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolError, ToolResult
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.tools.subagent import SubAgentCompletion
from deepseek_tui.utils import bind_tool, bind_turn

if TYPE_CHECKING:
    from deepseek_tui.integrations.hooks import HookContext
    from deepseek_tui.tools.runtime import ToolRuntime

logger = logging.getLogger(__name__)

# Skill 聚焦模式：当用户以 `/<skill-name>` 指定单个 skill 时，本 turn 只暴露
# 这套最小工具集，屏蔽无关工具的干扰。load_skill 必须在内，否则模型无法读取
# 聚焦 skill 的正文。
FOCUS_MODE_TOOLS = frozenset(
    {"read_file", "list_dir", "grep", "load_skill", "write_file", "edit_file"}
)


def _detect_focus_skill(text: str, registry: object | None) -> object | None:
    """解析形如 `/data-extract ...` 的前缀，命中已发现 skill 时返回该 Skill。

    仅识别整条消息**首个** token 为 `/<name>` 的情形；`<name>` 用 registry 的
    大小写不敏感查找（``SkillRegistry.get``）。未命中 / 无 registry 返回
    ``None``，调用方即回退到全量逻辑（把 `/xxx` 当普通文本，与现状一致）。
    """
    if registry is None:
        return None
    stripped = (text or "").lstrip()
    if not stripped.startswith("/"):
        return None
    first = stripped[1:].split(maxsplit=1)[0] if len(stripped) > 1 else ""
    if not first:
        return None
    return registry.get(first)


def _resolve_app_mode(mode: str) -> _AppMode:
    """Convert a mode string to AppMode, falling back to AGENT."""
    try:
        return _AppMode(mode)
    except ValueError:
        return _AppMode.AGENT


def _detect_locale(text: str) -> str:
    """Detect locale tag from user message text.

    Simple heuristic: if the message contains CJK characters (Chinese),
    return "zh". Otherwise return "en". This ensures the Environment
    block's ``lang`` field matches the user's language so the model
    responds in the same language.
    """
    if not text:
        return "en"
    cjk_count = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    # If >10% of non-space chars are CJK, treat as Chinese
    non_space = len(text.replace(" ", ""))
    if non_space > 0 and cjk_count / non_space > 0.1:
        return "zh"
    return "en"




def _clip_summary_line(text: str, limit: int = 200) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    if len(line) > limit:
        return line[: limit - 1] + "…"
    return line


def _format_checklist_entry(entry: object) -> str:
    if isinstance(entry, str) and entry.strip():
        return _clip_summary_line(entry, 80)
    if isinstance(entry, dict):
        content = entry.get("content") or entry.get("text")
        if isinstance(content, str) and content.strip():
            label = _clip_summary_line(content, 80)
            status = entry.get("status")
            if isinstance(status, str) and status.strip():
                return f"{label} [{status.strip()}]"
            return label
    return ""


def _summarize_checklist_args(arguments: dict[str, Any]) -> str:
    """Human-readable approval text for checklist / todo tool calls."""
    item_id = arguments.get("item_id")
    if item_id is not None and str(item_id).strip():
        parts = [f"checklist item #{item_id}"]
        status = arguments.get("status")
        if isinstance(status, str) and status.strip():
            parts.append(f"→ {status.strip()}")
        elif arguments.get("done") is True:
            parts.append("→ completed")
        elif arguments.get("done") is False:
            parts.append("→ pending")
        content = arguments.get("content") or arguments.get("text")
        if isinstance(content, str) and content.strip():
            parts.append(f": {_clip_summary_line(content, 120)}")
        return " ".join(parts)

    for key in ("todos", "items"):
        raw = arguments.get(key)
        if not isinstance(raw, list) or not raw:
            continue
        labels = [_format_checklist_entry(entry) for entry in raw]
        labels = [label for label in labels if label]
        if not labels:
            continue
        preview = "; ".join(labels[:3])
        if len(labels) > 3:
            preview += f"; +{len(labels) - 3} more"
        return f"checklist ({len(labels)} items): {preview}"
    return ""


def _summarize_call_args(arguments: dict[str, Any] | None) -> str:
    """Return a short, single-line summary of a tool's arguments.

    Used to enrich :class:`ApprovalRequest.input_summary` so the TUI
    approval dialog can show *what* is being approved (the actual
    command or path) rather than just the tool name. Picks the first
    non-empty value, takes its first line, and caps the length at 200.

    Prioritizes semantically important keys (prompt, command, path, etc.)
    over arbitrary parameter order to show the most relevant information.
    """
    if not arguments:
        return ""

    checklist_summary = _summarize_checklist_args(arguments)
    if checklist_summary:
        return checklist_summary

    # Priority keys that are most informative for approval decisions
    priority_keys = [
        "prompt", "message", "objective",  # Sub-agent / task descriptions
        "command", "cmd",                   # Shell commands
        "path", "file_path", "source_path", "dest_path",  # File operations
        "content", "text", "input",         # Content being written/sent
    ]

    # First pass: check priority keys
    for key in priority_keys:
        if key in arguments:
            value = arguments[key]
            if value is not None:
                s = str(value).strip()
                if s:
                    return _clip_summary_line(s)

    # Second pass: fallback to any non-empty value (skip checklist ids)
    skip_keys = {"item_id", "done"}
    for key, value in arguments.items():
        if key in skip_keys or value is None:
            continue
        s = str(value).strip()
        if not s:
            continue
        return _clip_summary_line(s)
    return ""


def _assistant_preface_text(message: Message | None) -> str | None:
    if message is None:
        return None
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            text = block.text.strip()
            if text:
                parts.append(text)
    joined = "\n".join(parts).strip()
    return joined or None


class Engine:
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

    async def _emit_tool_failure(
        self, tool_call: ToolCall, error_msg: str
    ) -> None:
        """Emit a failed tool result so the UI/runtime can close the tool item."""
        emit_tool_audit(
            {
                "event": "tool.result",
                "tool_id": tool_call.id,
                "tool_name": tool_call.name,
                "success": False,
                "error": error_msg,
            }
        )
        await self.handle.emit(
            ToolResultEvent(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=error_msg,
                success=False,
            )
        )

    def _build_tool_use_message(self, tool_calls: list[ToolCall]) -> Message:
        return Message.assistant_with_tools(
            [
                ToolUseBlock(id=tool_call.id, name=tool_call.name, input=tool_call.arguments)
                for tool_call in tool_calls
            ]
        )

    async def _execute_tool_calls(
        self, tool_calls: list[ToolCall], model: str | None = None
    ) -> list[Message]:
        results: list[Message] = []
        effective_model = model or self.default_model
        api_tools = await self._get_tools_with_mcp()

        # Build execution plans and check if batch can be parallelized
        # (mirrors Rust dispatch.rs:263-355 / turn_loop.rs:1184)
        if len(tool_calls) > 1:
            from deepseek_tui.engine.dispatch import (
                ToolExecutionPlan,
                mcp_tool_is_parallel_safe,
                mcp_tool_is_read_only,
            )
            plans = []
            for i, tc in enumerate(tool_calls):
                tool = (
                    self.tool_registry.get(tc.name)
                    if self.tool_registry.contains(tc.name) else None
                )
                from deepseek_tui.tools.approval import (
                    plan_requires_approval,
                    plan_requires_mcp_approval,
                )

                policy = self.exec_policy.approval_policy
                if tool is not None:
                    plans.append(ToolExecutionPlan(
                        index=i,
                        id=tc.id,
                        name=tc.name,
                        input=tc.arguments if isinstance(tc.arguments, dict) else {},
                        read_only=tool.is_read_only(),
                        supports_parallel=tool.is_read_only()
                        and tool.supports_parallel(),
                        approval_required=plan_requires_approval(tool, policy),
                    ))
                elif is_mcp_tool(tc.name):
                    plans.append(ToolExecutionPlan(
                        index=i,
                        id=tc.id,
                        name=tc.name,
                        input=tc.arguments if isinstance(tc.arguments, dict) else {},
                        read_only=mcp_tool_is_read_only(tc.name),
                        supports_parallel=mcp_tool_is_parallel_safe(tc.name),
                        approval_required=plan_requires_mcp_approval(tc.name, policy),
                    ))
                else:
                    plans.append(ToolExecutionPlan(
                        index=i,
                        id=tc.id,
                        name=tc.name,
                        input=tc.arguments if isinstance(tc.arguments, dict) else {},
                        read_only=False,
                        supports_parallel=False,
                        approval_required=False,
                    ))
            if should_parallelize_tool_batch(plans):
                logger.info("parallel_tool_batch size=%d", len(tool_calls))
                return await self._execute_tools_parallel(
                    tool_calls, api_tools, effective_model
                )

        for tool_call in tool_calls:
            with bind_tool(tool_call.id):
                args_preview = repr(tool_call.arguments)[:200]
                logger.info(
                    "tool_call_start name=%s args=%s",
                    tool_call.name,
                    args_preview,
                )
                tool_started = time.monotonic()
                try:
                    result = await self._execute_single_tool(
                        tool_call, api_tools, effective_model
                    )
                    duration_ms = int((time.monotonic() - tool_started) * 1000)
                    if result is None:
                        logger.warning(
                            "tool_denied name=%s duration_ms=%d",
                            tool_call.name,
                            duration_ms,
                        )
                        results.append(
                            Message.tool_result(
                                tool_call.id,
                                f"Tool {tool_call.name} denied by approval policy",
                                is_error=True,
                            )
                        )
                        continue

                    result = await self._maybe_elevate_and_retry_tool(
                        tool_call, api_tools, effective_model, result
                    )

                    logger.info(
                        "tool_call_end name=%s success=%s duration_ms=%d "
                        "content_bytes=%d",
                        tool_call.name,
                        result.success,
                        duration_ms,
                        len(result.content or ""),
                    )
                    emit_tool_audit(
                        {
                            "event": "tool.result",
                            "tool_id": tool_call.id,
                            "tool_name": tool_call.name,
                            "success": result.success,
                        }
                    )
                    if result.success:
                        self._mark_subagent_tool_result_consumed(
                            tool_call.name, result.metadata
                        )
                    self.working_set.observe_tool_call(
                        tool_call.name,
                        tool_call.arguments
                        if isinstance(tool_call.arguments, dict)
                        else None,
                        result.content,
                    )
                    await self.handle.emit(
                        ToolResultEvent(
                            tool_call_id=tool_call.id,
                            tool_name=tool_call.name,
                            content=result.content,
                            success=result.success,
                            metadata=(
                                dict(result.metadata)
                                if isinstance(result.metadata, dict)
                                else None
                            ),
                        )
                    )
                    if result.success:
                        await self._run_post_edit_lsp_hook(
                            tool_call.name, tool_call.arguments
                        )
                    from deepseek_tui.tools.runtime import apply_spillover

                    result = apply_spillover(result, tool_call.id)
                    output_for_context = compact_tool_result_for_context(
                        effective_model, tool_call.name, result
                    )
                    results.append(
                        Message.tool_result(
                            tool_call.id,
                            output_for_context,
                            is_error=not result.success,
                        )
                    )
                except ToolError as exc:
                    duration_ms = int((time.monotonic() - tool_started) * 1000)
                    error_msg = format_tool_error(exc, tool_call.name)
                    logger.warning(
                        "tool_call_error name=%s duration_ms=%d error=%s",
                        tool_call.name,
                        duration_ms,
                        error_msg,
                    )
                    await self._emit_tool_failure(tool_call, error_msg)
                    results.append(
                        Message.tool_result(
                            tool_call.id, f"Error: {error_msg}", is_error=True
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    duration_ms = int((time.monotonic() - tool_started) * 1000)
                    error_msg = f"{tool_call.name}: {type(exc).__name__}: {exc}"
                    logger.warning(
                        "tool_call_unexpected_error name=%s duration_ms=%d error=%s",
                        tool_call.name,
                        duration_ms,
                        error_msg,
                    )
                    await self._emit_tool_failure(tool_call, error_msg)
                    results.append(
                        Message.tool_result(
                            tool_call.id, f"Error: {error_msg}", is_error=True
                        )
                    )
        return results

    async def _execute_tools_parallel(
        self,
        tool_calls: list[ToolCall],
        api_tools: list[dict[str, Any]],
        model: str,
    ) -> list[Message]:
        """Execute multiple read-only tools in parallel.

        Mirrors Rust turn_loop.rs:1205-1303 (FuturesUnordered branch).
        Only called when should_parallelize_tool_batch returns True,
        which guarantees all tools are read-only, non-interactive,
        and don't require approval.
        """

        async def _exec_one_parallel(
            tool_call: ToolCall,
        ) -> tuple[ToolCall, ToolResult | None, str | None]:
            """Execute a single tool, returning (call, result, error_msg)."""
            with bind_tool(tool_call.id):
                args_preview = repr(tool_call.arguments)[:200]
                logger.info(
                    "tool_call_start name=%s args=%s (parallel)",
                    tool_call.name,
                    args_preview,
                )
                tool_started = time.monotonic()

                try:
                    result = await self._execute_single_tool(
                        tool_call, api_tools, model
                    )
                    duration_ms = int((time.monotonic() - tool_started) * 1000)

                    if result is None:
                        # Approval denied (shouldn't happen in parallel path)
                        logger.warning(
                            "tool_denied name=%s duration_ms=%d",
                            tool_call.name,
                            duration_ms,
                        )
                        return (
                            tool_call,
                            None,
                            f"Tool {tool_call.name} denied by approval policy",
                        )

                    logger.info(
                        "tool_call_end name=%s success=%s duration_ms=%d "
                        "content_bytes=%d (parallel)",
                        tool_call.name,
                        result.success,
                        duration_ms,
                        len(result.content or ""),
                    )
                    return (tool_call, result, None)

                except ToolError as exc:
                    duration_ms = int((time.monotonic() - tool_started) * 1000)
                    error_msg = format_tool_error(exc, tool_call.name)
                    logger.warning(
                        "tool_call_error name=%s duration_ms=%d error=%s (parallel)",
                        tool_call.name,
                        duration_ms,
                        error_msg,
                    )
                    return (tool_call, None, error_msg)

                except Exception as exc:  # noqa: BLE001
                    duration_ms = int((time.monotonic() - tool_started) * 1000)
                    error_msg = f"{tool_call.name}: {type(exc).__name__}: {exc}"
                    logger.warning(
                        "tool_call_unexpected_error name=%s duration_ms=%d error=%s (parallel)",
                        tool_call.name,
                        duration_ms,
                        error_msg,
                    )
                    return (tool_call, None, error_msg)

        # Execute all tools in parallel
        outcomes = await asyncio.gather(
            *[_exec_one_parallel(tc) for tc in tool_calls]
        )

        # Process outcomes and emit events (sequential, to preserve order)
        results: list[Message] = []
        for tool_call, result, error_msg in outcomes:
            if error_msg is not None:
                await self._emit_tool_failure(tool_call, error_msg)
                results.append(
                    Message.tool_result(
                        tool_call.id, f"Error: {error_msg}", is_error=True
                    )
                )
            elif result is None:
                # Denial case (shouldn't happen)
                results.append(
                    Message.tool_result(
                        tool_call.id,
                        f"Tool {tool_call.name} denied",
                        is_error=True,
                    )
                )
            else:
                # Success case
                emit_tool_audit(
                    {
                        "event": "tool.result",
                        "tool_id": tool_call.id,
                        "tool_name": tool_call.name,
                        "success": result.success,
                    }
                )
                if result.success:
                    self._mark_subagent_tool_result_consumed(
                        tool_call.name, result.metadata
                    )
                self.working_set.observe_tool_call(
                    tool_call.name,
                    tool_call.arguments
                    if isinstance(tool_call.arguments, dict)
                    else None,
                    result.content,
                )
                await self.handle.emit(
                    ToolResultEvent(
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        content=result.content,
                        success=result.success,
                        metadata=(
                            dict(result.metadata)
                            if isinstance(result.metadata, dict)
                            else None
                        ),
                    )
                )
                if result.success:
                    await self._run_post_edit_lsp_hook(
                        tool_call.name, tool_call.arguments
                    )
                from deepseek_tui.tools.runtime import apply_spillover

                result = apply_spillover(result, tool_call.id)
                output_for_context = compact_tool_result_for_context(
                    model, tool_call.name, result
                )
                results.append(
                    Message.tool_result(
                        tool_call.id,
                        output_for_context,
                        is_error=not result.success,
                    )
                )

        return results

    _SNAPSHOT_TOOLS: frozenset[str] = frozenset(
        {"write_file", "edit_file", "apply_patch"}
    )

    def _take_pre_tool_snapshot(
        self, tool_call_id: str, tool_name: str, args: dict[str, Any]
    ) -> None:
        """Capture file contents before a write tool runs (mirrors Rust #384).

        Best-effort — failures here must never block tool execution.
        """
        if tool_name not in self._SNAPSHOT_TOOLS:
            return
        from deepseek_tui.integrations.lsp import edited_paths_for_tool

        try:
            paths = edited_paths_for_tool(tool_name, args)
        except Exception:  # noqa: BLE001
            return
        workspace = self.tool_context.working_directory
        snapshots: list[tuple[Path, bytes | None]] = []
        for p in paths:
            absolute = p if p.is_absolute() else workspace / p
            try:
                size = absolute.stat().st_size
                if size > self._max_snapshot_file_size:
                    continue
                snapshots.append((absolute, absolute.read_bytes()))
            except FileNotFoundError:
                snapshots.append((absolute, None))
            except OSError:
                continue
        if snapshots:
            self.tool_snapshots[tool_call_id] = snapshots
            while len(self.tool_snapshots) > self._max_tool_snapshots:
                oldest = next(iter(self.tool_snapshots))
                del self.tool_snapshots[oldest]

    def undo_last_tool(self) -> tuple[bool, str]:
        """Restore the most recent tool snapshot (mirrors Rust /undo).

        Returns (success, message).
        """
        if not self.tool_snapshots:
            return False, "No tool snapshots available to undo."
        last_id = next(reversed(self.tool_snapshots))
        snapshots = self.tool_snapshots.pop(last_id)
        restored = 0
        errors: list[str] = []
        for path, original in snapshots:
            try:
                if original is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.write_bytes(original)
                restored += 1
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        if errors:
            return False, f"Restored {restored}; errors: {'; '.join(errors)}"
        return True, f"Reverted {restored} file(s) from tool {last_id[:8]}"

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

    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        api_tools: list[dict[str, Any]],
        model: str,
    ) -> ToolResult | None:
        """Execute a single tool call, handling special tools and approval."""
        hook_ctx = self._lifecycle_hook_context(
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            model=model,
        )
        await self._run_lifecycle_hook("tool_call_before", hook_ctx)
        # Expose parent transcript for fork_context spawns (Rust SubAgentForkContext).
        self.tool_context.metadata["parent_session_messages"] = [
            m.model_dump(mode="json") for m in self.session_messages
        ]
        from deepseek_tui.engine.usage_ledger import usage_source
        # usage_source("tool") 是一个上下文管理器，把这期间产生的 token 用量都归类到 "tool" 来源
        with usage_source("tool"):
            result = await self._execute_single_tool_impl(tool_call, api_tools, model)
        # 累计子代理 token 成本 + 回填 hook 结果
        if result is not None:
            self._accrue_child_token_cost_from_metadata(result.metadata)
            hook_ctx.tool_result = result.content
            hook_ctx.tool_success = result.success
        await self._run_lifecycle_hook("tool_call_after", hook_ctx)
        return result

    async def _execute_single_tool_impl(
        self,
        tool_call: ToolCall,
        api_tools: list[dict[str, Any]],
        model: str,
    ) -> ToolResult | None:
        """Inner tool dispatch (lifecycle hooks handled by wrapper)."""
        from deepseek_tui.mcp.execute import normalize_mcp_bridge_tool_name

        # 先归一化：把 Rust 桥接别名（如 mcp_read_resource）映射回注册表工具名，
        # 后续的 is_external_mcp_tool 判定才会把它正确归到注册表分支而非外部 MCP 分支。
        tool_name = normalize_mcp_bridge_tool_name(tool_call.name)
        # 写文件类工具执行前拍快照（供 /undo）。注意：parallel 自身不是写工具，
        # 这里不会拍；其子工具的快照由 _execute_parallel_tools 逐个走完整分发时各自拍。
        self._take_pre_tool_snapshot(tool_call.id, tool_name, tool_call.arguments)

        # --- Special built-in tools (not in ToolRegistry) ---
        if is_tool_search_tool(tool_name):
            active: set[str] = set()
            for t in api_tools:
                fn = t.get("function", t)
                if isinstance(fn, dict):
                    name = fn.get("name", "")
                    if isinstance(name, str):
                        active.add(name)
            return execute_tool_search(
                tool_name, tool_call.arguments, api_tools, active
            )

        if tool_name == CODE_EXECUTION_TOOL_NAME:
            # Arbitrary local Python execution must go through the same
            # approval gate as registry tools with EXECUTES_CODE.
            from deepseek_tui.tools.approval import (
                approval_request_for_capabilities,
            )
            from deepseek_tui.tools.registry import ToolCapability

            approval_request = approval_request_for_capabilities(
                tool_name,
                [ToolCapability.EXECUTES_CODE],
                self.exec_policy.approval_policy,
                reason="Execute model-provided Python code in a local subprocess",
            )
            if approval_request is not None:
                denied = await self._handle_approval_flow(tool_call, approval_request)
                if denied:
                    return None
            return await execute_code_execution_tool(
                tool_call.arguments, self.tool_context.working_directory
            )

        if tool_name == MULTI_TOOL_PARALLEL_NAME:
            return await self._execute_parallel_tools(tool_call.arguments)

        if tool_name == REQUEST_USER_INPUT_NAME:
            return await self._await_user_input(tool_call.id, tool_call.arguments)

        # --- External MCP tools (mcp_<server>_<tool>) ---
        from deepseek_tui.mcp.execute import (
            execute_external_mcp_tool,
            is_external_mcp_tool,
        )
        from deepseek_tui.tools.approval import approval_request_for_mcp

        if is_external_mcp_tool(tool_name, self.tool_registry.contains(tool_name)):
            # 仅当 mcp_<server>_<tool> 形态、且不在注册表、也不是 read-resource 别名时走此分支；
            # read-resource 已被上面 normalize 改写为注册表工具名，会落到下方注册表分支。
            if self.mcp_manager is None:
                raise ToolError(f"MCP tool '{tool_name}' called but no MCP manager configured")
            approval_request = approval_request_for_mcp(
                tool_name, self.exec_policy.approval_policy
            )
            if approval_request is not None:
                denied = await self._handle_approval_flow(
                    tool_call, approval_request
                )
                if denied:
                    return None
            return await execute_external_mcp_tool(
                self.mcp_manager,
                tool_name,
                tool_call.arguments,
            )

        # --- Normal registry tools ---
        if not self.tool_registry.contains(tool_name):
            raise ToolError(missing_tool_error_message(tool_name, api_tools))

        tool = self.tool_registry.get(tool_name)

        from deepseek_tui.tools.approval import approval_request_for_tool

        approval_request = approval_request_for_tool(
            tool, self.exec_policy.approval_policy
        )
        if approval_request is not None:
            denied = await self._handle_approval_flow(tool_call, approval_request)
            if denied:
                return None

        if tool_name == "workflow":
            # workflow 工具需要回调进引擎（取消事件、进度/状态上报），通过 metadata 临时注入。
            # 注意：审批门在此之前已执行，被拒会直接 return None，不会走到注入这一步。
            self.tool_context.metadata["engine_cancel_event"] = self.handle.cancel_event
            self.tool_context.metadata["workflow_tool_call_id"] = tool_call.id

            def _workflow_emit(ev: WorkflowProgressEvent) -> None:
                if not self.handle.try_emit(ev):
                    if getattr(ev, "completed", False):
                        logger.warning(
                            "workflow_completed_event_dropped queue_full"
                        )

            self.tool_context.metadata["workflow_emit"] = _workflow_emit

            def _workflow_status(message: str) -> None:
                self.handle.try_emit(StatusEvent(message))

            self.tool_context.metadata["workflow_status_cb"] = _workflow_status
        try:
            return await self.tool_registry.execute(
                tool_name, tool_call.arguments, self.tool_context
            )
        finally:
            # 无论 execute 是否抛异常，都清掉临时注入的 metadata，避免污染下一次工具调用。
            # pop(..., None) 保证即使因 workflow 未走注入分支也不会 KeyError。
            if tool_name == "workflow":
                self.tool_context.metadata.pop("engine_cancel_event", None)
                self.tool_context.metadata.pop("workflow_tool_call_id", None)
                self.tool_context.metadata.pop("workflow_emit", None)
                self.tool_context.metadata.pop("workflow_status_cb", None)

    async def _handle_approval_flow(
        self,
        tool_call: ToolCall,
        approval_request: Any,
    ) -> bool:
        """Run the approval gate. Returns True if denied."""
        from deepseek_tui.tools.approval import NEVER_BLOCKED_PREFIX
        from deepseek_tui.tools.approval import enrich_approval_request

        cache_key = build_approval_key(tool_call.name, tool_call.arguments)
        cache_status = self.approval_cache.check(cache_key)

        if cache_status is ApprovalCacheStatus.APPROVED:
            logger.info(
                "approval_cache_hit tool=%s reason=cached_session", tool_call.name
            )
            await self.handle.emit(
                ApprovalResolvedEvent(
                    tool_call_id=tool_call.id,
                    approved=True,
                    reason="cached_session",
                )
            )
            return False

        logger.info(
            "approval_required tool=%s risk=%s",
            tool_call.name,
            getattr(approval_request, "risk_level", None),
        )
        blocked_reason = getattr(approval_request, "reason", "") or ""
        if blocked_reason.startswith(NEVER_BLOCKED_PREFIX):
            emit_tool_audit(
                {
                    "event": "tool.approval_decision",
                    "tool_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "decision": ApprovalDecision.DENIED.value,
                }
            )
            await self.handle.emit(
                ApprovalResolvedEvent(
                    tool_call_id=tool_call.id,
                    approved=False,
                    reason=blocked_reason,
                )
            )
            await self.handle.emit(
                SandboxDeniedEvent(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    reason=blocked_reason,
                )
            )
            return True
        args = (
            tool_call.arguments
            if isinstance(tool_call.arguments, dict)
            else {}
        )
        enrich_approval_request(
            approval_request,
            tool_call.name,
            args,
            tool_description=approval_request.reason,
        )
        # Auto-approve short-circuits inside request_approval without ever
        # registering the id on the ApprovalBridge. Emitting
        # ApprovalRequiredEvent in that case races the instant decision:
        # the UI shows a card / auto-responds, POSTs
        # /v1/approvals/{id} for an id the bridge never knew, and gets 404.
        # Only surface the approval request when someone can actually answer.
        auto_approved = await self.approval_handler.auto_approve_enabled()
        if not auto_approved:
            emit_tool_audit(
                {
                    "event": "tool.approval_required",
                    "tool_id": tool_call.id,
                    "tool_name": tool_call.name,
                }
            )
            await self.handle.emit(
                ApprovalRequiredEvent(
                    tool_call_id=tool_call.id,
                    request=approval_request,
                )
            )
        decision = await self.approval_handler.request_approval(
            tool_call.id, approval_request
        )
        logger.info(
            "approval_decision tool=%s decision=%s", tool_call.name, decision.value
        )
        approved = decision in {
            ApprovalDecision.APPROVED,
            ApprovalDecision.APPROVED_SESSION,
        }
        emit_tool_audit(
            {
                "event": "tool.approval_decision",
                "tool_id": tool_call.id,
                "tool_name": tool_call.name,
                "decision": decision.value,
            }
        )
        await self.handle.emit(
            ApprovalResolvedEvent(
                tool_call_id=tool_call.id,
                approved=approved,
                reason=decision.value,
            )
        )
        if decision is ApprovalDecision.DENIED:
            await self.handle.emit(
                SandboxDeniedEvent(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    reason=f"Tool {tool_call.name} denied by approval policy",
                )
            )
            return True

        self.approval_cache.insert(
            cache_key,
            approved_for_session=(decision is ApprovalDecision.APPROVED_SESSION),
        )
        self.exec_policy.record_decision(tool_call.name, decision)
        return False

    @staticmethod
    def _is_sandbox_denied_tool_result(tool_name: str, result: ToolResult) -> bool:
        if tool_name not in (
            "exec_shell",
            "exec_shell_wait",
            "exec_shell_interact",
        ):
            return False
        meta = result.metadata if isinstance(result.metadata, dict) else {}
        return bool(meta.get("sandbox_denied"))

    async def _maybe_elevate_and_retry_tool(
        self,
        tool_call: ToolCall,
        api_tools: list[dict[str, Any]],
        model: str,
        result: ToolResult,
    ) -> ToolResult:
        """L3: offer one-shot sandbox elevation when Seatbelt denies exec_shell."""
        if not self._is_sandbox_denied_tool_result(tool_call.name, result):
            return result
        if self.tool_context.elevated_sandbox_policy is not None:
            return result

        from deepseek_tui.server.approval import (
            ElevationBridge,
            PendingElevationRecord,
        )
        from deepseek_tui.policy.sandbox import (
            elevation_kind_label,
            sandbox_policy_for_mode,
            suggest_elevation_policy,
        )

        bridge = self.tool_context.metadata.get("elevation_bridge")
        if not isinstance(bridge, ElevationBridge):
            return result

        policy = self.tool_context.execution_sandbox_policy
        if policy is None:
            policy = sandbox_policy_for_mode(
                self.mode, self.tool_context.working_directory
            )

        meta = result.metadata if isinstance(result.metadata, dict) else {}
        denial_msg = str(
            meta.get("denial_message") or result.content or "Sandbox blocked command"
        )
        elevated = suggest_elevation_policy(
            policy,
            denial_msg,
            workspace=self.tool_context.working_directory,
        )
        if elevated is None:
            return result

        cmd_preview = ""
        if isinstance(tool_call.arguments, dict):
            raw_cmd = tool_call.arguments.get("command")
            if isinstance(raw_cmd, str):
                cmd_preview = raw_cmd[:500]

        kind = elevation_kind_label(elevated)
        event = ElevationRequiredEvent(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            reason=denial_msg,
            elevation_kind=kind,
            command_preview=cmd_preview,
        )
        await self.handle.emit(event)

        thread_id = str(self.tool_context.metadata.get("runtime_thread_id", ""))
        fut = bridge.register(
            tool_call.id,
            meta=PendingElevationRecord(
                thread_id=thread_id,
                tool_name=tool_call.name,
                reason=denial_msg,
                elevation_kind=kind,
                command_preview=cmd_preview,
            ),
        )
        try:
            approved = await asyncio.wait_for(fut, timeout=600.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            approved = False

        if not approved:
            await self.handle.emit(
                SandboxDeniedEvent(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    reason="Sandbox elevation denied by user",
                )
            )
            return ToolResult(
                success=False,
                content=f"Sandbox elevation denied. {denial_msg}".strip(),
                metadata=result.metadata,
            )

        prev = self.tool_context.elevated_sandbox_policy
        self.tool_context.elevated_sandbox_policy = elevated
        try:
            retry = await self._execute_single_tool(tool_call, api_tools, model)
        finally:
            self.tool_context.elevated_sandbox_policy = prev
        return retry if retry is not None else result

    def _save_crash_checkpoint(
        self,
        messages: list[Message],
        *,
        model: str,
    ) -> None:
        """Write ``latest.json`` before a turn — mirrors ``save_checkpoint``."""
        try:
            from deepseek_tui.state.session import save_checkpoint

            save_checkpoint(
                {
                    "metadata": {
                        "id": self._cycle_session_id,
                        "workspace": str(
                            self.tool_context.working_directory.resolve()
                        ),
                        "model": model,
                    },
                    "model": model,
                    "turn_counter": self.turn_counter,
                    "messages": [m.model_dump() for m in messages],
                }
            )
        except Exception:  # noqa: BLE001
            logger.debug("checkpoint save failed", exc_info=True)

    async def _maybe_layered_context_checkpoint(
        self, messages: list[Message], model: str
    ) -> None:
        """Pre-request soft seam — mirrors ``layered_context_checkpoint`` (#159).
        阈值分级(seam.py:23-31),按当前输入 token 递进,每级只触发一次、且必须按序:

        L1 = 192K、L2 = 384K、L3 = 576K
        对应产物字数上限逐级收紧:800 / 600 / 400 词
        """
        seam = self.seam_manager
        if seam is None or not seam.config.enabled:
            return

        # Prefer the provider's real input_tokens (zero estimation error);
        # fall back to the char-based estimate on the first turn only.
        # Same fix as should_compact — the estimate undercounts ~6x and
        # made seam's L1 (192K) unreachable in practice.
        tokens = self.last_real_input_tokens
        if tokens <= 0:
            from deepseek_tui.engine.context import estimated_input_tokens

            try:
                tokens = estimated_input_tokens(messages)
            except Exception:  # noqa: BLE001
                return
        highest = await seam.highest_level()
        level = seam.seam_level_for(tokens, highest)
        if level is None:
            return
        msg_count = len(messages)
        verbatim_start = seam.verbatim_window_start(msg_count)
        if verbatim_start <= 0:
            return
        pinned = self.working_set.pinned_message_indices(
            messages, self.tool_context.working_directory
        )
        try:
            existing = seam.collect_seam_texts(messages)
            from deepseek_tui.engine.usage_ledger import usage_source

            with usage_source("seam"):
                if existing:
                    recent = messages[:verbatim_start]
                    seam_text = await seam.recompact(
                        existing, recent, level, 0, verbatim_start
                    )
                else:
                    seam_text = await seam.produce_soft_seam(
                        messages,
                        level,
                        0,
                        verbatim_start,
                        pinned_indices=sorted(pinned),
                    )
        except Exception as err:  # noqa: BLE001
            logger.warning("layered_context_checkpoint failed: %s", err)
            return
        if seam_text and seam_text.strip():
            # Insert seam at verbatim window boundary — between old messages
            # and recent verbatim turns. This preserves prefix cache (no
            # deletion of prior messages) while placing the summary where
            # the LLM can use it as a bridge between stale prefix and fresh
            # context.
            messages.insert(verbatim_start, Message.assistant(seam_text))

    async def _auto_persist_session(self) -> None:
        """Best-effort session persistence after each turn.

        Writes session_messages to a JSON file so sessions survive restarts.
        Mirrors Rust ``Engine::auto_save_session`` behavior. Silent on failure.
        """
        try:
            from deepseek_tui.config.paths import user_sessions_dir

            sessions_dir = user_sessions_dir()
            sessions_dir.mkdir(parents=True, exist_ok=True)
            session_file = sessions_dir / "current.json"
            import json as _json

            data = {
                "model": self.default_model,
                "turn_counter": self.turn_counter,
                "messages": [m.model_dump() for m in self.session_messages],
                "compaction_summary_prompt": self._compaction_summary_prompt,
                "metadata": {
                    "id": self._cycle_session_id,
                },
            }
            tmp = session_file.with_suffix(".tmp")
            tmp.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(session_file)
        except Exception:  # noqa: BLE001
            pass

    _COMPACTION_SUMMARY_MAX_CHARS = 20_000

    def _record_compaction_summary(self, summary_prompt: str | None) -> None:
        """Accumulate a compaction summary so later turns retain it.

        Keeps the tail when the accumulated text exceeds the cap (newer
        summaries are more relevant than older ones).
        """
        if not summary_prompt:
            return
        if self._compaction_summary_prompt:
            combined = f"{self._compaction_summary_prompt}\n\n{summary_prompt}"
        else:
            combined = summary_prompt
        if len(combined) > self._COMPACTION_SUMMARY_MAX_CHARS:
            combined = combined[-self._COMPACTION_SUMMARY_MAX_CHARS :]
        self._compaction_summary_prompt = combined

    async def _run_compaction(
        self, messages: list[Message]
    ) -> CompactionResult:
        """Run compaction and return the full result (incl. success flag).

        Shared by :meth:`_emergency_compact` (TurnLoop callback, which
        only wants the messages) and the manual ``/compact`` path in
        ``threads.py`` (which needs ``success`` to surface failures to
        the user).
        """
        from deepseek_tui.engine.usage_ledger import usage_source

        with usage_source("compaction"):
            result = await compact_messages_safe(
                self.client,
                messages,
                self.compaction_config,
                workspace=self.tool_context.working_directory,
                model_override=self.default_model,
            )
        # Persist the summary — previously discarded, so emergency/manual
        # compaction lost the archived history entirely.
        self._record_compaction_summary(result.summary_prompt)
        return result

    async def _emergency_compact(self, messages: list[Message]) -> list[Message]:
        """Emergency compaction callback for TurnLoop context overflow recovery."""
        result = await self._run_compaction(messages)
        return result.messages

    async def _maybe_advance_cycle(
        self, messages: list[Message], model: str
    ) -> None:
        """Archive a full cycle to disk and trim history when threshold crossed.

        Produces a model-curated briefing via produce_briefing (or Flash seam
        briefing if seams exist) so the next cycle starts with context about
        decisions, constraints, and progress from the archived history.
        """
        if not messages:
            return

        # Prefer the provider's real input_tokens (zero estimation error);
        # fall back to the char-based estimate on the first turn only.
        # Same fix as should_compact — the estimate undercounts ~6x and
        # made cycle's 768K threshold unreachable in practice.
        active_tokens = self.last_real_input_tokens
        if active_tokens <= 0:
            from deepseek_tui.engine.context import estimated_input_tokens

            try:
                active_tokens = estimated_input_tokens(messages)
            except Exception:  # noqa: BLE001 — token estimation is best-effort
                return
        if not should_advance_cycle(
            active_tokens,
            reserved_headroom_tokens=8_000,
            model=model,
            config=self.cycle_config,
            in_flight=False,
        ):
            return
        logger.info(
            "cycle_advance_triggered cycle_n=%d active_tokens=%d msg_count=%d",
            self._cycle_n,
            active_tokens,
            len(messages),
        )
        try:
            archive_path = archive_cycle(
                session_id=self._cycle_session_id,
                cycle_n=self._cycle_n,
                messages=list(messages),
                model=model,
                started=self._cycle_started_at,
            )
            logger.info("cycle_archived path=%s", archive_path)
        except OSError as exc:
            logger.warning("cycle_archive_failed error=%s", exc)
            return

        # --- Produce briefing for the next cycle ---
        briefing_text = ""
        from deepseek_tui.engine.cycle import (
            CycleBriefing,
            StructuredState,
            build_seed_messages,
            produce_briefing,
        )
        from deepseek_tui.engine.usage_ledger import usage_source

        # Build structured state snapshot
        structured = StructuredState(
            mode_label=self.mode or "agent",
            workspace=str(self.tool_context.working_directory),
            working_set_summary=self.working_set.summary() or None,
        )
        structured_block = structured.to_system_block()

        # Try Flash briefing from seams first (cheap); fall back to full
        # produce_briefing if no seams or if Flash fails.
        try:
            with usage_source("cycle_briefing"):
                if self.seam_manager is not None:
                    existing_seams = self.seam_manager.collect_seam_texts(messages)
                    if existing_seams:
                        briefing_text = await self.seam_manager.produce_flash_briefing(
                            existing_seams, structured_state=structured_block
                        )
                if not briefing_text:
                    briefing_text = await produce_briefing(
                        self.client,
                        model,
                        messages,
                        self.cycle_config.briefing_max_for(model),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cycle_briefing_failed error=%s", exc)
            # Continue without briefing — still better than crashing

        # Assemble seed messages for the new cycle
        from deepseek_tui.engine.context import estimate_tokens

        briefing_obj = None
        if briefing_text:
            briefing_obj = CycleBriefing(
                cycle=self._cycle_n,
                timestamp=int(time.time()),
                briefing_text=briefing_text,
                token_estimate=estimate_tokens(briefing_text),
            )

        seed_dicts = build_seed_messages(
            structured_state_block=structured_block,
            briefing=briefing_obj,
            pending_user_message=None,
        )

        # Convert seed dicts to Message objects and preserve recent messages.
        # When the briefing came back empty (Flash refused, timed out, or no
        # seams existed), preserving only 4 recent messages would silently
        # discard the entire pre-cycle history with no replacement. Fall back
        # to a larger verbatim window so the next cycle at least has recent
        # context to work from, and warn so the empty briefing is observable.
        if briefing_text:
            keep = min(4, len(messages))
        else:
            keep = min(16, len(messages))
            logger.warning(
                "cycle_briefing_empty fallback_keep=%d/%d — preserving extra "
                "recent messages because briefing generation produced no text",
                keep, len(messages),
            )

        recent = messages[-keep:]

        messages.clear()
        for sd in seed_dicts:
            role = sd["role"]
            content = sd["content"]
            if role == "user":
                messages.append(Message.user(content))
            else:
                messages.append(Message.assistant(content))
        messages.extend(recent)

        # Reset seam tracking for the new cycle
        if self.seam_manager is not None:
            await self.seam_manager.reset()

        self._cycle_n += 1
        self._cycle_started_at = int(time.time())
        logger.info(
            "cycle_advanced new_cycle=%d seed_msgs=%d briefing_tokens=%d",
            self._cycle_n,
            len(messages),
            estimate_tokens(briefing_text) if briefing_text else 0,
        )

    # --- Engine-intercepted special tools --------------------------------

    async def _execute_parallel_tools(self, input_data: dict[str, Any]) -> ToolResult:
        """Fan out multi_tool_use.parallel sub-calls concurrently.

        Mirrors Rust turn_loop.rs:1161-1189 + tool_execution.rs:58-67.
        Only read-only tools that don't require approval are eligible.
        Recursive self-calls are rejected (tool_execution.rs:63).
        """
        calls = parse_parallel_tool_calls(input_data)
        if not calls:
            raise ToolError(
                "multi_tool_use.parallel: no valid tool_uses entries — each "
                "entry must be an object with recipient_name and parameters"
            )

        async def _run_one(name: str, params: dict[str, Any]) -> dict[str, str]:
            if name == MULTI_TOOL_PARALLEL_NAME:
                return {
                    "tool": name,
                    "error": "multi_tool_use.parallel cannot call itself",
                    "success": "false",
                }
            if not self.tool_registry.contains(name):
                return {
                    "tool": name,
                    "error": f"Tool '{name}' not found",
                    "success": "false",
                }
            tool = self.tool_registry.get(name)
            if not tool.is_read_only():
                return {
                    "tool": name,
                    "error": f"Tool '{name}' is not read-only; denied",
                    "success": "false",
                }
            try:
                result = await self.tool_registry.execute(
                    name, params, self.tool_context
                )
                return {"tool": name, "content": result.content, "success": "true"}
            except (ToolError, Exception) as exc:
                return {"tool": name, "error": str(exc), "success": "false"}

        import json as _json

        results = await asyncio.gather(*[_run_one(n, p) for n, p in calls])
        all_failed = all(r.get("success") == "false" for r in results)
        return ToolResult(
            content=_json.dumps(results, ensure_ascii=False),
            success=not all_failed,
        )

    async def _await_user_input(
        self, tool_call_id: str, input_data: dict[str, Any]
    ) -> ToolResult:
        """Emit UserInputRequiredEvent and block until TUI resolves.

        Mirrors Rust turn_loop.rs:1245-1275.
        """
        from deepseek_tui.tools.user_input import validate_user_input_request

        questions = validate_user_input_request(input_data)
        questions_payload: list[dict[str, object]] = [
            {
                "header": q.header,
                "id": q.id,
                "question": q.question,
                "options": q.options,
            }
            for q in questions
        ]

        # Create a future the TUI will resolve
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self.handle.pending_user_inputs[tool_call_id] = future

        await self.handle.emit(
            UserInputRequiredEvent(
                tool_call_id=tool_call_id,
                questions=questions_payload,
            )
        )

        cancel_wait = asyncio.create_task(
            self.handle.cancel_event.wait(), name="user-input-cancel-wait"
        )
        try:
            done, _ = await asyncio.wait(
                {future, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if future not in done:
                # Turn was cancelled while waiting for user input.
                future.cancel()
                return ToolResult(
                    content="User input request cancelled (turn cancelled)",
                    success=False,
                )
            response = future.result()
        finally:
            cancel_wait.cancel()
            self.handle.pending_user_inputs.pop(tool_call_id, None)

        import json as _json

        return ToolResult(content=_json.dumps(response, ensure_ascii=False), success=True)

    # --- Stage 4.4 post-edit LSP hooks --------------------------------

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
