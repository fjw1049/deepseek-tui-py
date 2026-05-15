from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.approval import ApprovalHandler, AutoApprovalHandler
from deepseek_tui.engine.capacity import CapacityController, CapacityControllerConfig
from deepseek_tui.engine.capacity_flow import (
    run_error_escalation_checkpoint,
    run_post_tool_checkpoint,
    run_pre_request_checkpoint,
)
from deepseek_tui.engine.compaction import (
    CompactionConfig,
    compact_messages_safe,
    should_compact,
)
from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.engine.cycle_manager import (
    CycleConfig,
    archive_cycle,
    should_advance_cycle,
)
from deepseek_tui.engine.dispatch import format_tool_error
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ErrorEvent,
    SandboxDeniedEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.ops import CancelRequestOp, SendMessageOp
from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.engine.seam_manager import SeamConfig, SeamManager
from deepseek_tui.engine.tool_catalog import (
    CODE_EXECUTION_TOOL_NAME,
    MULTI_TOOL_PARALLEL_NAME,
    REQUEST_USER_INPUT_NAME,
    execute_code_execution_tool,
    execute_tool_search,
    is_tool_search_tool,
    missing_tool_error_message,
)
from deepseek_tui.engine.tool_execution import emit_tool_audit
from deepseek_tui.engine.turn_loop import TurnLoop, TurnResult
from deepseek_tui.engine.working_set import WorkingSet
from deepseek_tui.execpolicy.approval_cache import (
    ApprovalCache,
    ApprovalCacheStatus,
    build_approval_key,
)
from deepseek_tui.execpolicy.engine import ExecPolicyEngine
from deepseek_tui.execpolicy.models import ApprovalDecision
from deepseek_tui.lsp import (
    LSP_MANAGER_KEY,
    DiagnosticBlock,
    LspManager,
    edited_paths_for_tool,
    render_blocks,
)
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.base import ToolError, ToolResult
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.trace import bind_tool, bind_turn

if TYPE_CHECKING:
    from deepseek_tui.tools.runtime import ToolRuntime

logger = logging.getLogger(__name__)


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
                    s = s.splitlines()[0]
                    if len(s) > 200:
                        s = s[:199] + "…"
                    return s

    # Second pass: fallback to any non-empty value
    for value in arguments.values():
        if value is None:
            continue
        s = str(value).strip()
        if not s:
            continue
        s = s.splitlines()[0]
        if len(s) > 200:
            s = s[:199] + "…"
        return s
    return ""


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
    ) -> None:
        self.handle = handle
        self.client = client
        self.default_model = default_model
        # When a full runtime is supplied, it wins — unpack registry + context
        # from it so managers stay paired with the context they own.
        if tool_runtime is not None:
            self.tool_registry = tool_runtime.registry
            self.tool_context = tool_runtime.context
        else:
            self.tool_registry = tool_registry or ToolRegistry()
            self.tool_context = tool_context or ToolContext(working_directory=Path.cwd())
        self.tool_runtime = tool_runtime
        # Ensure the registry dispatcher can see the context (Stage 3
        # managers are attached on the context, not the registry).
        self.tool_registry.set_context(self.tool_context)
        self.exec_policy = exec_policy or ExecPolicyEngine()
        self.approval_handler = approval_handler or AutoApprovalHandler()
        self.max_tool_round_trips = max_tool_round_trips
        self.compaction_config = compaction_config or CompactionConfig()
        self.capacity_controller = CapacityController(config=CapacityControllerConfig())
        self.session_messages: list[Message] = []
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
        # Stage 3.next.1 approval cache — fingerprints repeat tool calls
        # so an APPROVED_SESSION grant doesn't have to re-prompt.
        self.approval_cache = ApprovalCache()
        self._tool_write_lock = asyncio.Lock()
        # Skills integration — renders available skills into system prompt
        self.skill_registry = skill_registry
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
    ) -> Engine:
        """Construct an Engine with a freshly-wired :class:`ToolRuntime`.

        This is the integration-complete path: all managers (task/subagent),
        the full registry, and the ToolContext are created together so that
        tools can actually reach the managers at dispatch time.
        """
        from deepseek_tui.config.models import Config
        from deepseek_tui.skills import discover_in_workspace
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = config if isinstance(config, Config) else Config()
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=working_directory,
            mode=mode,
        )
        # Discover skills for system prompt injection
        skill_reg = discover_in_workspace(workspace=working_directory)
        # Pull sampling / reasoning defaults out of Config so the per-turn
        # MessageRequest carries them all the way to DeepSeekClient.
        provider_cfg = cfg.effective_provider_config()
        engine = cls(
            handle=handle,
            client=client,
            default_model=default_model,
            exec_policy=exec_policy,
            approval_handler=approval_handler,
            max_tool_round_trips=max_tool_round_trips,
            tool_runtime=runtime,
            skill_registry=skill_reg,
            default_reasoning_effort=cfg.reasoning_effort,
            default_temperature=provider_cfg.temperature,
            default_top_p=None,
            default_extra_body=dict(provider_cfg.extra_body or {}),
        )
        # Cycle / Seam wiring (off by default). Honors ``Config.cycle_enabled``
        # and ``Config.seam_enabled`` once those fields exist; today they
        # default to False so behavior is unchanged from the pre-batch state.
        engine.cycle_config = CycleConfig(
            enabled=bool(getattr(cfg, "cycle_enabled", False)),
        )
        if bool(getattr(cfg, "seam_enabled", False)):
            engine.seam_manager = SeamManager(
                flash_client=client, config=SeamConfig(enabled=True)
            )
        engine._cycle_session_id = uuid.uuid4().hex
        engine._cycle_started_at = int(time.time())
        return engine

    def _render_skills_context(self) -> str | None:
        """Render skills context for system prompt injection."""
        if self.skill_registry is None:
            return None
        from deepseek_tui.skills import render_available_skills_context

        return render_available_skills_context(self.skill_registry) or None

    def context_breakdown(self, model: str | None = None) -> dict[str, int]:
        """Estimate token occupancy by category for the next request.

        Returns ``{bucket_name: tokens, ..., "total": int, "window": int}``.
        Buckets:

        - ``system_prompt`` — full system prompt body (incl. skills section)
        - ``tools`` — JSON schema of every tool the registry will send
        - ``conversation`` — accumulated user/assistant/tool messages
        - ``free`` — derived as ``window - total``, clamped at 0

        ``window`` reads ``context_window_for_model``; ``model`` defaults
        to ``self.default_model``.

        Token counts use the same conservative ``len*1.5`` estimator as
        :func:`engine.context.estimated_input_tokens` so the numbers
        match what the capacity / compaction subsystems already act on.
        """
        import json as _json

        from deepseek_tui.config.provider_registry import context_window_for_model
        from deepseek_tui.engine.context import (
            _estimate_text_tokens_conservative,
            estimated_input_tokens,
        )
        from deepseek_tui.engine.prompts import build_system_prompt

        target_model = model or self.default_model

        system_text = build_system_prompt(
            None,
            skills_context=self._render_skills_context(),
            working_set_summary=self.working_set.summary() or None,
        )
        system_tokens = _estimate_text_tokens_conservative(system_text)

        try:
            api_tools = self.tool_registry.to_api_tools()
        except Exception:  # noqa: BLE001 — registry may raise during boot
            api_tools = []
        tools_json = _json.dumps(api_tools, ensure_ascii=False)
        tools_tokens = _estimate_text_tokens_conservative(tools_json)

        conv_tokens = (
            estimated_input_tokens(self.session_messages)
            if self.session_messages
            else 0
        )

        total = system_tokens + tools_tokens + conv_tokens
        window = context_window_for_model(target_model) or 0
        free = max(0, window - total) if window else 0

        return {
            "system_prompt": system_tokens,
            "tools": tools_tokens,
            "conversation": conv_tokens,
            "total": total,
            "window": window,
            "free": free,
        }

    async def shutdown(self) -> None:
        """Drain managers owned by the tool runtime if Engine built it."""
        if self.tool_runtime is not None:
            await self.tool_runtime.shutdown()
        if hasattr(self.client, "close"):
            await self.client.close()

    async def run(self) -> None:
        logger.info(
            "engine_run_start model=%s session_id=%s",
            self.default_model,
            self._cycle_session_id,
        )
        try:
            while True:
                op = await self.handle.next_op()
                if isinstance(op, SendMessageOp):
                    await self._handle_send_message(op)
                elif isinstance(op, CancelRequestOp):
                    logger.info("engine_cancel_request reason=%s", op.reason)
                    # Defense in depth: ensure the cancel_event is set even if
                    # the caller queued the op without calling handle.cancel().
                    # ``handle.cancel()`` already sets it before enqueuing, but
                    # any direct ``send_op(CancelRequestOp(...))`` previously
                    # silently dropped the cancellation. TurnLoop checks the
                    # event each chunk, so setting it here propagates cancel
                    # into any in-flight stream. Mirrors Rust which routes
                    # cancel through the same op channel.
                    self.handle.cancel_event.set()
                    continue
        except asyncio.CancelledError:
            logger.info("engine_run_cancelled")
            raise

    async def _handle_send_message(self, op: SendMessageOp) -> None:
        with bind_turn() as turn_id:
            self.handle.reset_cancel()
            self.handle._mark_turn_active()
            try:
                await self._handle_send_message_inner(op, turn_id)
            finally:
                self.handle._mark_turn_idle()

    async def _handle_send_message_inner(
        self, op: SendMessageOp, turn_id: str
    ) -> None:
        user_message = Message.user(op.content)
        working_messages = [*self.session_messages, user_message]
        self.working_set.observe_user_message(op.content or "")
        preview = (op.content or "")[:200].replace("\n", " ")
        logger.info(
            "turn_start user_text_len=%d preview=%r model=%s session_msgs=%d",
            len(op.content or ""),
            preview,
            op.model or self.default_model,
            len(self.session_messages),
        )
        start = time.monotonic()

        await self.handle.emit(TurnStartedEvent(user_text=op.content))
        result = await self._run_conversation(
            messages=working_messages,
            model=op.model or self.default_model,
            system_prompt=build_system_prompt(
                op.system_prompt,
                skills_context=self._render_skills_context(),
                working_set_summary=self.working_set.summary() or None,
            ),
            max_tokens=op.max_tokens,
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        if result.cancelled:
            logger.info(
                "turn_cancelled turn=%s duration_ms=%d", turn_id, duration_ms
            )
            await self.handle.emit(TurnCancelledEvent(reason="user_cancelled"))
            return

        self.session_messages = working_messages
        usage = result.usage
        logger.info(
            "turn_complete duration_ms=%d input_tokens=%s output_tokens=%s "
            "cache_hit=%s reasoning_tokens=%s tool_calls=%d",
            duration_ms,
            getattr(usage, "input_tokens", 0) if usage else 0,
            getattr(usage, "output_tokens", 0) if usage else 0,
            getattr(usage, "cache_read_input_tokens", 0) if usage else 0,
            getattr(usage, "reasoning_tokens", 0) if usage else 0,
            len(result.tool_calls or []),
        )
        # Accumulate session cost from the DeepSeek usage payload.
        # Hidden when pricing is unknown (off-platform providers,
        # unrecognised model) — the UI also hides the chip in that
        # case so we don't show $0.00 misleadingly.
        cache_hit_tokens = 0
        cache_miss_tokens = 0
        cost_usd: float | None = None
        cost_cny: float | None = None
        if usage is not None:
            # Accumulate cache hit/miss across the session so the
            # status-bar chip reflects "how much prompt traffic the
            # cache has saved you so far" instead of "what fraction
            # of this single turn was a prefix hit" (the latter is
            # nearly always 99%+ on a multi-turn DeepSeek session
            # and conveys no information).
            self.session_cache_hit_total += usage.cache_read_input_tokens
            self.session_cache_miss_total += usage.cache_creation_input_tokens
            cache_hit_tokens = self.session_cache_hit_total
            cache_miss_tokens = self.session_cache_miss_total
            from deepseek_tui.client.pricing import (
                calculate_turn_cost_estimate_from_usage,
            )

            model_for_pricing = op.model or self.default_model
            estimate = calculate_turn_cost_estimate_from_usage(
                model_for_pricing, usage
            )
            if estimate is not None:
                self.session_cost_usd += estimate.usd
                self.session_cost_cny += estimate.cny
                cost_usd = self.session_cost_usd
                cost_cny = self.session_cost_cny
        await self.handle.emit(
            TurnCompleteEvent(
                assistant_message=result.assistant_message,
                usage=result.usage,
                session_cost_usd=cost_usd,
                session_cost_cny=cost_cny,
                cache_hit_tokens=cache_hit_tokens,
                cache_miss_tokens=cache_miss_tokens,
            )
        )
        await self._auto_persist_session()

    async def _run_conversation(
        self,
        messages: list[Message],
        model: str,
        system_prompt: str,
        max_tokens: int | None,
    ) -> TurnResult:
        tools = self.tool_registry.to_api_tools()
        self.turn_counter += 1
        step_error_count = 0
        consecutive_tool_error_steps = 0
        # Cycle boundary check (opt-in). When the active input grows past
        # ``cycle_config.threshold_for(model)``, archive the cycle to disk
        # and continue with a trimmed message list. Best-effort — failures
        # never block the conversation.
        if self.cycle_config.enabled:
            await self._maybe_advance_cycle(messages, model)
        for round_idx in range(self.max_tool_round_trips + 1):
            logger.info(
                "round_start round=%d msg_count=%d tools_count=%d model=%s",
                round_idx,
                len(messages),
                len(tools),
                model,
            )
            # Drain steer messages — mid-turn user input (mirrors turn_loop.rs:49-57)
            for steer_text in self.handle.drain_steers():
                steer_text = steer_text.strip()
                if steer_text:
                    logger.info("steer_injected text_len=%d", len(steer_text))
                    messages.append(Message.user(steer_text))

            # Capacity pre-request checkpoint (mirrors capacity_flow.rs:13-34)
            await run_pre_request_checkpoint(
                self.capacity_controller,
                self.turn_counter,
                model,
                messages,
                compact_fn=self._emergency_compact,
            )

            # Hard cap: force compaction when message count is excessive,
            # as a memory safety net. The token-based threshold (500K floor)
            # handles normal compaction; this catches pathological cases where
            # many small messages accumulate without hitting the token floor.
            if len(messages) > 500 or should_compact(messages, self.compaction_config):
                logger.info(
                    "compact_triggered before_count=%d", len(messages)
                )
                compact_result = await compact_messages_safe(
                    self.client,
                    messages,
                    self.compaction_config,
                    workspace=self.tool_context.working_directory,
                    model_override=model,
                )
                messages[:] = compact_result.messages
                logger.info(
                    "compact_done after_count=%d summary_attached=%s",
                    len(messages),
                    bool(compact_result.summary_prompt),
                )
                if compact_result.summary_prompt:
                    system_prompt = f"{system_prompt}\n\n{compact_result.summary_prompt}"

            # Flush any diagnostics queued by post-edit hooks from the
            # previous round-trip so the model sees them on this request.
            self._flush_pending_lsp_diagnostics(messages)
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
            result = await self.turn_loop.run(
                request, self.handle.emit, self.handle.cancel_event, tools=tools
            )
            if result.cancelled:
                return result
            if result.assistant_message is not None:
                messages.append(result.assistant_message)
            if not result.tool_calls:
                return result

            messages.append(self._build_tool_use_message(result.tool_calls))
            tool_results = await self._execute_tool_calls(result.tool_calls, model)
            tool_errors = sum(1 for m in tool_results if any(
                getattr(b, "is_error", False) for b in m.content if hasattr(b, "is_error")
            ))
            messages.extend(tool_results)

            # Capacity post-tool checkpoint (mirrors capacity_flow.rs:37-76)
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
        api_tools = self.tool_registry.to_api_tools()

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
                        )
                    )
                    if result.success:
                        await self._run_post_edit_lsp_hook(
                            tool_call.name, tool_call.arguments
                        )
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
                    emit_tool_audit(
                        {
                            "event": "tool.result",
                            "tool_id": tool_call.id,
                            "tool_name": tool_call.name,
                            "success": False,
                            "error": error_msg,
                        }
                    )
                    await self.handle.emit(ErrorEvent(message=error_msg, retryable=False))
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
                    emit_tool_audit(
                        {
                            "event": "tool.result",
                            "tool_id": tool_call.id,
                            "tool_name": tool_call.name,
                            "success": False,
                            "error": error_msg,
                        }
                    )
                    await self.handle.emit(ErrorEvent(message=error_msg, retryable=False))
                    results.append(
                        Message.tool_result(
                            tool_call.id, f"Error: {error_msg}", is_error=True
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
        from deepseek_tui.lsp import edited_paths_for_tool

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

    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        api_tools: list[dict[str, Any]],
        model: str,
    ) -> ToolResult | None:
        """Execute a single tool call, handling special tools and approval.

        Returns None if the tool was denied by approval.
        """
        tool_name = tool_call.name
        # Snapshot before file-modifying tools
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
            return await execute_code_execution_tool(
                tool_call.arguments, self.tool_context.working_directory
            )

        if tool_name == MULTI_TOOL_PARALLEL_NAME:
            return await self._execute_parallel_tools(tool_call.arguments)

        if tool_name == REQUEST_USER_INPUT_NAME:
            return await self._await_user_input(tool_call.id, tool_call.arguments)

        # --- Normal registry tools ---
        if not self.tool_registry.contains(tool_name):
            raise ToolError(missing_tool_error_message(tool_name, api_tools))

        tool = self.tool_registry.get(tool_name)

        # Approval gate
        approval_request = self.exec_policy.evaluate(
            tool_name, tool.capabilities()
        )
        if approval_request is not None:
            denied = await self._handle_approval_flow(tool_call, approval_request)
            if denied:
                return None

        return await self.tool_registry.execute(
            tool_name, tool_call.arguments, self.tool_context
        )

    async def _handle_approval_flow(
        self,
        tool_call: ToolCall,
        approval_request: Any,
    ) -> bool:
        """Run the approval gate. Returns True if denied."""
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
        # The TUI approval dialog needs to surface *what* is being
        # approved — "exec_shell + medium risk" is useless on its own.
        # Populate ``input_summary`` from the tool arguments here so the
        # downstream ApprovalHandler can show the actual command/path.
        if not getattr(approval_request, "input_summary", ""):
            summary = _summarize_call_args(tool_call.arguments)
            if summary:
                try:
                    approval_request.input_summary = summary
                except Exception:  # noqa: BLE001 — frozen models, etc.
                    pass
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
            }
            tmp = session_file.with_suffix(".tmp")
            tmp.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(session_file)
        except Exception:  # noqa: BLE001
            pass

    async def _emergency_compact(self, messages: list[Message]) -> list[Message]:
        """Emergency compaction callback for TurnLoop context overflow recovery."""
        result = await compact_messages_safe(
            self.client,
            messages,
            self.compaction_config,
            workspace=self.tool_context.working_directory,
            model_override=self.default_model,
        )
        return result.messages

    async def _maybe_advance_cycle(
        self, messages: list[Message], model: str
    ) -> None:
        """Archive a full cycle to disk and trim history when threshold crossed.

        Mirrors Rust ``Engine::maybe_advance_cycle`` (engine.rs:887-888) at the
        wiring level. The Rust version produces a model-curated briefing via
        ``produce_briefing``; this minimal port uses a structured-state seed
        (no LLM call) so it works offline. The deeper ``produce_briefing``
        path stays available — see ``cycle_manager.produce_briefing`` — and is
        documented in HANDOVER as a follow-up.
        """
        if not messages:
            return
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
        # Replace history with a minimal seed so the next request fits the
        # window. The verbatim window of recent turns is preserved.
        keep = min(8, len(messages))
        seed = messages[-keep:]
        messages.clear()
        messages.extend(seed)
        self._cycle_n += 1
        self._cycle_started_at = int(time.time())

    # --- Engine-intercepted special tools --------------------------------

    async def _execute_parallel_tools(self, input_data: dict[str, Any]) -> ToolResult:
        """Fan out multi_tool_use.parallel sub-calls concurrently.

        Mirrors Rust turn_loop.rs:1161-1189 + tool_execution.rs:58-67.
        Only read-only tools that don't require approval are eligible.
        Recursive self-calls are rejected (tool_execution.rs:63).
        """
        tool_uses = input_data.get("tool_uses")
        if not isinstance(tool_uses, list) or not tool_uses:
            raise ToolError("tool_uses must be a non-empty array")

        async def _run_one(item: dict[str, Any]) -> dict[str, str]:
            name = item.get("recipient_name", "")
            params = item.get("parameters", {})
            if not isinstance(params, dict):
                params = {}
            for prefix in ("functions.", "tools.", "tool."):
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
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

        results = await asyncio.gather(*[_run_one(item) for item in tool_uses])
        return ToolResult(content=_json.dumps(results, ensure_ascii=False), success=True)

    async def _await_user_input(
        self, tool_call_id: str, input_data: dict[str, Any]
    ) -> ToolResult:
        """Emit UserInputRequiredEvent and block until TUI resolves.

        Mirrors Rust turn_loop.rs:1245-1275.
        """
        from deepseek_tui.tools.user_input_tool import validate_user_input_request

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

        try:
            response = await future
        finally:
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
