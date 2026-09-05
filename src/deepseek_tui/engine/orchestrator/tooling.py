"""Tool-execution half of the Engine (mixin).

Sequential + parallel tool dispatch, approval/elevation flow, and
interactive user-input waits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.engine.dispatch import (
    emit_tool_audit,
    format_tool_error,
    is_mcp_tool,
    should_parallelize_tool_batch,
)
from deepseek_tui.engine.tool_dedup import ToolCallDeduplicator
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ElevationRequiredEvent,
    ModeChangedEvent,
    SandboxDeniedEvent,
    ToolResultEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.tools import (
    PLAN_MODE_TOOL_ALLOWLIST,
    REQUEST_USER_INPUT_NAME,
    missing_tool_error_message,
)
from deepseek_tui.tools.plan_mode import (
    ENTER_PLAN_MODE_NAME,
    EXIT_ACCEPT_AGENT,
    EXIT_ACCEPT_YOLO,
    EXIT_LEAVE,
    EXIT_PLAN_MODE_NAME,
    EXIT_REVISE,
    enter_plan_questions,
    exit_plan_questions,
    parse_enter_plan_response,
    parse_exit_plan_response,
    plan_file_exists,
)
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.approval import (
    ApprovalCacheStatus,
    ApprovalDecision,
    build_approval_key,
)
from deepseek_tui.tools.registry import ToolError, ToolResult
from deepseek_tui.utils import bind_tool

logger = logging.getLogger(__name__)


def _normalise_tool_call(name: str, arguments: Any) -> tuple[str, Any]:
    """Map wire/legacy aliases to the registry name used for dispatch."""
    from deepseek_tui.engine.dispatch import normalize_legacy_tool_call
    from deepseek_tui.mcp.execute import normalize_mcp_bridge_tool_name

    return normalize_legacy_tool_call(
        normalize_mcp_bridge_tool_name(name), arguments
    )


def _allowed_tool_names(api_tools: list[dict[str, Any]]) -> set[str]:
    """Canonical names from the exact catalog sent with this request."""
    names: set[str] = set()
    for definition in api_tools:
        function = definition.get("function") or definition
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and name:
            names.add(_normalise_tool_call(name, {})[0])
    return names


class ToolExecutionMixin:
    """Tool dispatch / approval / elevation methods shared into Engine."""

    # Populated by Engine.__init__; declared here for type-checkers / mixins.
    _tool_dedup: ToolCallDeduplicator

    async def _emit_tool_failure(self, tool_call: ToolCall, error_msg: str) -> None:
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

    def _ingress_pressure_ratio(self, model: str) -> float | None:
        """How full the context was on the request that asked for these tools.

        Deliberately the real token count and nothing else: ``None`` when the
        provider has not reported one yet, so ingress truncation falls back
        to its fixed limits rather than trusting the estimate path, which is
        known to run low and would talk it into being generous at exactly the
        wrong moment.
        """
        if self.last_real_input_tokens <= 0:
            return None
        from deepseek_tui.config.providers import context_window_for_model

        window = context_window_for_model(model)
        if window <= 0:
            return None
        return self.last_real_input_tokens / window

    def _build_tool_use_message(self, tool_calls: list[ToolCall]) -> Message:
        return Message.assistant_with_tools(
            [
                ToolUseBlock(id=tool_call.id, name=tool_call.name, input=tool_call.arguments)
                for tool_call in tool_calls
            ]
        )

    def _mcp_declared_capabilities(self, tool_name: str) -> list[str]:
        """Capability hints declared for an MCP tool's server (plugin
        manifest ``permissions``); empty when unknown / undeclared."""
        if self.mcp_manager is None:
            return []
        return self.mcp_manager.declared_capabilities(tool_name)

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        model: str | None = None,
    ) -> list[Message]:
        results: list[Message] = []
        effective_model = model or self.default_model
        api_tools = getattr(self, "_active_api_tools", None)
        if api_tools is None:
            api_tools = await self._get_tools_with_mcp()
        self._tool_dedup.begin_batch()

        try:
            # Build execution plans and check if batch can be parallelized.
            # Duplicate fingerprints fall back to the sequential path so reuse /
            # force-stop stay single-threaded and ordered.
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
                        if self.tool_registry.contains(tc.name)
                        else None
                    )
                    from deepseek_tui.tools.approval import (
                        plan_requires_approval,
                        plan_requires_mcp_approval,
                    )

                    policy = self.exec_policy.approval_policy
                    if tool is not None:
                        args = tc.arguments if isinstance(tc.arguments, dict) else {}
                        read_only = tool.is_read_only_for_input(args)
                        plans.append(
                            ToolExecutionPlan(
                                index=i,
                                id=tc.id,
                                name=tc.name,
                                input=args,
                                read_only=read_only,
                                supports_parallel=read_only and tool.supports_parallel(),
                                approval_required=plan_requires_approval(tool, policy, args),
                            )
                        )
                    elif is_mcp_tool(tc.name):
                        plans.append(
                            ToolExecutionPlan(
                                index=i,
                                id=tc.id,
                                name=tc.name,
                                input=tc.arguments if isinstance(tc.arguments, dict) else {},
                                read_only=mcp_tool_is_read_only(tc.name),
                                supports_parallel=mcp_tool_is_parallel_safe(tc.name),
                                approval_required=plan_requires_mcp_approval(
                                    tc.name,
                                    policy,
                                ),
                            )
                        )
                    else:
                        plans.append(
                            ToolExecutionPlan(
                                index=i,
                                id=tc.id,
                                name=tc.name,
                                input=tc.arguments if isinstance(tc.arguments, dict) else {},
                                read_only=False,
                                supports_parallel=False,
                                approval_required=False,
                            )
                        )
                has_dup_keys = self._tool_dedup.batch_has_duplicate_keys(
                    [
                        (
                            tc.name,
                            tc.arguments if isinstance(tc.arguments, dict) else {},
                        )
                        for tc in tool_calls
                    ]
                )
                if should_parallelize_tool_batch(plans) and not has_dup_keys:
                    logger.info("parallel_tool_batch size=%d", len(tool_calls))
                    return await self._execute_tools_parallel(
                        tool_calls, api_tools, effective_model
                    )

            goal_terminal = False
            for tool_call in tool_calls:
                if goal_terminal:
                    content = "Goal reached a terminal state; skipped later tool call."
                    await self._emit_tool_failure(tool_call, content)
                    results.append(Message.tool_result(tool_call.id, content, is_error=True))
                    continue
                decision = self._tool_dedup.classify(
                    tool_call.name,
                    tool_call.arguments if isinstance(tool_call.arguments, dict) else {},
                )
                if decision.kind == "reuse":
                    content = self._tool_dedup.reuse_content(decision)
                    logger.info(
                        "tool_call_dedup_reuse name=%s tool_id=%s",
                        tool_call.name,
                        tool_call.id,
                    )
                    await self.handle.emit(
                        ToolResultEvent(
                            tool_call_id=tool_call.id,
                            tool_name=tool_call.name,
                            content=content,
                            success=not decision.reuse_is_error,
                        )
                    )
                    results.append(
                        Message.tool_result(
                            tool_call.id,
                            content,
                            is_error=decision.reuse_is_error,
                        )
                    )
                    continue
                if decision.kind == "block":
                    content = self._tool_dedup.block_content(decision)
                    logger.warning(
                        "tool_call_dedup_blocked name=%s streak=%d tool_id=%s",
                        tool_call.name,
                        decision.projected_streak,
                        tool_call.id,
                    )
                    await self._emit_tool_failure(tool_call, content)
                    self._tool_dedup.record(decision.key, content, is_error=True)
                    results.append(Message.tool_result(tool_call.id, content, is_error=True))
                    continue

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
                            denied = f"Tool {tool_call.name} denied by approval policy"
                            self._tool_dedup.record(decision.key, denied, is_error=True)
                            denied = self._tool_dedup.decorate_execute_content(decision, denied)
                            results.append(
                                Message.tool_result(
                                    tool_call.id,
                                    denied,
                                    is_error=True,
                                )
                            )
                            continue

                        result = await self._maybe_elevate_and_retry_tool(
                            tool_call, api_tools, effective_model, result
                        )

                        logger.info(
                            "tool_call_end name=%s success=%s duration_ms=%d content_bytes=%d",
                            tool_call.name,
                            result.success,
                            duration_ms,
                            len(result.content or ""),
                        )
                        result = await self._finish_tool_result(
                            tool_call, decision, result, effective_model, results
                        )
                        goal_terminal = (
                            result.success
                            and tool_call.name == "UpdateGoal"
                            and isinstance(tool_call.arguments, dict)
                            and tool_call.arguments.get("status") in {"complete", "blocked"}
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
                        await self._finish_tool_error(tool_call, decision, error_msg, results)
                    except Exception as exc:  # noqa: BLE001
                        duration_ms = int((time.monotonic() - tool_started) * 1000)
                        error_msg = f"{tool_call.name}: {type(exc).__name__}: {exc}"
                        logger.warning(
                            "tool_call_unexpected_error name=%s duration_ms=%d error=%s",
                            tool_call.name,
                            duration_ms,
                            error_msg,
                        )
                        await self._finish_tool_error(tool_call, decision, error_msg, results)
            return results

        finally:
            self._tool_dedup.end_batch()

    async def _finish_tool_result(
        self,
        tool_call: ToolCall,
        decision: Any,
        result: ToolResult,
        model: str,
        results: list[Message],
    ) -> ToolResult:
        """Shared success-path post-processing for one executed tool.

        Both the sequential and parallel tool loops run this identical
        chain: consumption bookkeeping, result event, LSP hook, spillover,
        ingress compaction, dedup record/decorate, and the tool_result
        message. Returns the post-spillover result.
        """
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
                tool_call.name,
                result.metadata,
                tool_call.arguments if isinstance(tool_call.arguments, dict) else None,
            )
        self._mark_process_tool_result_consumed(
            tool_call.name,
            result.metadata if isinstance(result.metadata, dict) else None,
            tool_call.arguments if isinstance(tool_call.arguments, dict) else None,
        )
        self.working_set.observe_tool_call(
            tool_call.name,
            tool_call.arguments if isinstance(tool_call.arguments, dict) else None,
        )
        await self.handle.emit(
            ToolResultEvent(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=result.content,
                success=result.success,
                metadata=(dict(result.metadata) if isinstance(result.metadata, dict) else None),
            )
        )
        if result.success:
            await self._run_post_edit_lsp_hook(tool_call.name, tool_call.arguments)
        from deepseek_tui.tools.runtime import apply_spillover

        result = apply_spillover(result, tool_call.id)
        output_for_context = compact_tool_result_for_context(
            model,
            tool_call.name,
            result,
            pressure_ratio=self._ingress_pressure_ratio(model),
        )
        self._tool_dedup.record(
            decision.key,
            output_for_context,
            is_error=not result.success,
        )
        output_for_context = self._tool_dedup.decorate_execute_content(decision, output_for_context)
        results.append(
            Message.tool_result(
                tool_call.id,
                output_for_context,
                is_error=not result.success,
            )
        )
        return result

    async def _finish_tool_error(
        self,
        tool_call: ToolCall,
        decision: Any,
        error_msg: str,
        results: list[Message],
    ) -> None:
        """Shared error-path post-processing: emit, record, append."""
        await self._emit_tool_failure(tool_call, error_msg)
        err_content = f"Error: {error_msg}"
        self._tool_dedup.record(decision.key, err_content, is_error=True)
        err_content = self._tool_dedup.decorate_execute_content(decision, err_content)
        results.append(Message.tool_result(tool_call.id, err_content, is_error=True))

    async def _execute_tools_parallel(
        self,
        tool_calls: list[ToolCall],
        api_tools: list[dict[str, Any]],
        model: str,
    ) -> list[Message]:
        """Execute multiple read-only tools in parallel.

        Only called when should_parallelize_tool_batch returns True,
        which guarantees all tools are read-only, non-interactive,
        and don't require approval. Callers must also ensure the batch
        has no duplicate fingerprints (those use the sequential path).
        """
        from deepseek_tui.engine.tool_dedup import DedupDecision

        decisions: list[DedupDecision] = []
        runnable: list[ToolCall] = []
        for tool_call in tool_calls:
            decision = self._tool_dedup.classify(
                tool_call.name,
                tool_call.arguments if isinstance(tool_call.arguments, dict) else {},
            )
            decisions.append(decision)
            if decision.kind == "block":
                continue
            runnable.append(tool_call)

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
                    result = await self._execute_single_tool(tool_call, api_tools, model)
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

        outcomes = (
            await asyncio.gather(*[_exec_one_parallel(tc) for tc in runnable]) if runnable else []
        )
        outcome_by_id = {tc.id: (tc, result, err) for tc, result, err in outcomes}

        # Process outcomes and emit events (sequential, to preserve order)
        results: list[Message] = []
        for tool_call, decision in zip(tool_calls, decisions, strict=True):
            if decision.kind == "block":
                content = self._tool_dedup.block_content(decision)
                logger.warning(
                    "tool_call_dedup_blocked name=%s streak=%d tool_id=%s (parallel batch)",
                    tool_call.name,
                    decision.projected_streak,
                    tool_call.id,
                )
                await self._emit_tool_failure(tool_call, content)
                self._tool_dedup.record(decision.key, content, is_error=True)
                results.append(Message.tool_result(tool_call.id, content, is_error=True))
                continue

            _tc, result, error_msg = outcome_by_id[tool_call.id]
            if error_msg is not None:
                await self._finish_tool_error(tool_call, decision, error_msg, results)
            elif result is None:
                # Denial case (shouldn't happen)
                denied = f"Tool {tool_call.name} denied"
                self._tool_dedup.record(decision.key, denied, is_error=True)
                denied = self._tool_dedup.decorate_execute_content(decision, denied)
                results.append(
                    Message.tool_result(
                        tool_call.id,
                        denied,
                        is_error=True,
                    )
                )
            else:
                await self._finish_tool_result(tool_call, decision, result, model, results)

        return results

    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        api_tools: list[dict[str, Any]],
        model: str,
    ) -> ToolResult | None:
        """Execute a single tool call, handling special tools and approval."""
        tool_name, _arguments = _normalise_tool_call(
            tool_call.name, tool_call.arguments
        )
        if tool_name not in _allowed_tool_names(api_tools):
            raise ToolError(missing_tool_error_message(tool_call.name, api_tools))

        hook_ctx = self._lifecycle_hook_context(
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            model=model,
        )
        pre_hook_results = await self._run_lifecycle_hook("tool_call_before", hook_ctx)
        if pre_hook_results:
            from deepseek_tui.integrations.hooks import aggregate_hook_decision

            decision = aggregate_hook_decision(pre_hook_results)
            if decision.blocked:
                # PreToolUse deny / exit-2: the tool never runs; the reason
                # is returned to the model as a failed tool result so it can
                # adjust (Claude Code hook semantics).
                reason = decision.reason or "Tool call blocked by a PreToolUse hook"
                emit_tool_audit(
                    {
                        "event": "tool.hook_blocked",
                        "tool_id": tool_call.id,
                        "tool_name": tool_call.name,
                    }
                )
                return ToolResult(
                    success=False,
                    content=f"Tool call blocked by hook: {reason}",
                )
            if decision.ask:
                # permissionDecision "ask": escalate to the user through the
                # regular approval gate regardless of the tool's own policy.
                from deepseek_tui.tools.approval import build_approval_request

                approval_request = build_approval_request(
                    tool_call.name,
                    [],
                    reason=decision.reason or "A PreToolUse hook requested user confirmation",
                )
                denied = await self._handle_approval_flow(tool_call, approval_request)
                if denied:
                    return ToolResult(
                        success=False,
                        content="Tool call denied by the user (hook escalation)",
                    )
        # Expose parent transcript for fork_context spawns.
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
        post_hook_results = await self._run_lifecycle_hook("tool_call_after", hook_ctx)
        if post_hook_results and result is not None:
            from deepseek_tui.integrations.hooks import aggregate_hook_decision

            decision = aggregate_hook_decision(post_hook_results)
            feedback: list[str] = []
            if decision.blocked and decision.reason:
                # PostToolUse block is non-reverting: the tool already ran.
                # The reason is appended so the model sees the objection.
                feedback.append(decision.reason)
            feedback.extend(decision.additional_context)
            if feedback:
                from dataclasses import replace as _dc_replace

                result = _dc_replace(
                    result,
                    content=result.content + "\n\n[hook feedback]\n" + "\n".join(feedback),
                )
        return result

    async def _execute_single_tool_impl(
        self,
        tool_call: ToolCall,
        api_tools: list[dict[str, Any]],
        model: str,
    ) -> ToolResult | None:
        """Inner tool dispatch (lifecycle hooks handled by wrapper)."""
        # Map bridge/legacy aliases before policy checks and registry dispatch.
        tool_name, arguments = _normalise_tool_call(tool_call.name, tool_call.arguments)
        # 写文件类工具执行前拍快照（供 /undo）。
        self._take_pre_tool_snapshot(tool_call.id, tool_name, tool_call.arguments)

        if tool_name == REQUEST_USER_INPUT_NAME:
            return await self._await_user_input(tool_call.id, tool_call.arguments)

        if tool_name == ENTER_PLAN_MODE_NAME:
            return await self._handle_enter_plan_mode(tool_call.id)

        if tool_name == EXIT_PLAN_MODE_NAME:
            return await self._handle_exit_plan_mode(tool_call.id)

        mode = (self.mode or "agent").strip() or "agent"
        if mode == "plan" and tool_name not in PLAN_MODE_TOOL_ALLOWLIST:
            raise ToolError(
                f"Tool '{tool_name}' is unavailable in plan mode "
                "(read-only). Finish with exit_plan_mode when the plan is ready."
            )

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
                tool_name,
                self.exec_policy.approval_policy,
                self._mcp_declared_capabilities(tool_name),
            )
            if approval_request is not None:
                denied = await self._handle_approval_flow(tool_call, approval_request)
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
            tool,
            self.exec_policy.approval_policy,
            arguments if isinstance(arguments, dict) else None,
        )
        if approval_request is not None:
            # Fingerprint the *normalized* call so legacy names share the
            # same cache entry as their merged successors (and so
            # task_shell_start lands on shell:<command>, not a bare tool key).
            denied = await self._handle_approval_flow(
                tool_call,
                approval_request,
                fingerprint_name=tool_name,
                fingerprint_arguments=arguments,
            )
            if denied:
                return None

        return await self.tool_registry.execute(tool_name, arguments, self.tool_context)

    async def _handle_approval_flow(
        self,
        tool_call: ToolCall,
        approval_request: Any,
        *,
        fingerprint_name: str | None = None,
        fingerprint_arguments: Any = None,
    ) -> bool:
        """Run the approval gate. Returns True if denied.

        ``fingerprint_name`` / ``fingerprint_arguments`` should be the
        post-normalization pair (what will actually execute). UI / audit
        events still use the original ``tool_call`` name so the user sees
        what the model invoked.
        """
        from deepseek_tui.tools.approval import NEVER_BLOCKED_PREFIX
        from deepseek_tui.tools.approval import enrich_approval_request

        fp_name = fingerprint_name if fingerprint_name is not None else tool_call.name
        fp_args = (
            fingerprint_arguments if fingerprint_arguments is not None else tool_call.arguments
        )
        cache_key = build_approval_key(fp_name, fp_args)
        cache_status = self.approval_cache.check(cache_key)

        if cache_status is ApprovalCacheStatus.APPROVED:
            logger.info("approval_cache_hit tool=%s reason=cached_session", tool_call.name)
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
        # Enrich from the normalized args so previews / approval_key match
        # execution semantics (e.g. task_shell_start → shell command).
        enrich_args = fp_args if isinstance(fp_args, dict) else {}
        enrich_approval_request(
            approval_request,
            fp_name,
            enrich_args,
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
        decision = await self.approval_handler.request_approval(tool_call.id, approval_request)
        logger.info("approval_decision tool=%s decision=%s", tool_call.name, decision.value)
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
        return False

    @staticmethod
    def _is_sandbox_denied_tool_result(tool_name: str, result: ToolResult) -> bool:
        if tool_name not in (
            "exec_shell",
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
            policy = sandbox_policy_for_mode(self.mode, self.tool_context.working_directory)

        meta = result.metadata if isinstance(result.metadata, dict) else {}
        denial_msg = str(meta.get("denial_message") or result.content or "Sandbox blocked command")
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
        # Auto-approve / trust_mode skip the UI elevation card — same contract
        # as tool approvals: never emit a request the user cannot answer.
        auto_elevated = bool(getattr(self.tool_context, "trust_mode", False))
        if not auto_elevated:
            handler = getattr(self, "approval_handler", None)
            if handler is not None and hasattr(handler, "auto_approve_enabled"):
                try:
                    auto_elevated = bool(await handler.auto_approve_enabled())
                except Exception:  # noqa: BLE001
                    auto_elevated = False

        if auto_elevated:
            approved = True
        else:
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
            except asyncio.TimeoutError:
                approved = False
            except asyncio.CancelledError:
                # Hard cancel must not be reinterpreted as "user denied elevation".
                raise

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

    async def _await_user_input(self, tool_call_id: str, input_data: dict[str, Any]) -> ToolResult:
        """Emit UserInputRequiredEvent and block until TUI resolves."""
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
        response = await self._await_user_input_raw(tool_call_id, questions_payload, purpose=None)
        if response is None:
            return ToolResult(
                content="User input request cancelled (turn cancelled)",
                success=False,
            )
        import json as _json

        return ToolResult(content=_json.dumps(response, ensure_ascii=False), success=True)

    async def _await_user_input_raw(
        self,
        tool_call_id: str,
        questions_payload: list[dict[str, object]],
        *,
        purpose: str | None,
    ) -> dict[str, Any] | None:
        """Block on a UserInputRequiredEvent; None means cancelled."""
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self.handle.pending_user_inputs[tool_call_id] = future
        await self.handle.emit(
            UserInputRequiredEvent(
                tool_call_id=tool_call_id,
                questions=questions_payload,
                purpose=purpose,
            )
        )
        cancel_wait = asyncio.create_task(
            self.handle.cancel_event.wait(), name="user-input-cancel-wait"
        )
        try:
            done, _ = await asyncio.wait({future, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)
            if future not in done:
                future.cancel()
                return None
            return future.result()
        finally:
            cancel_wait.cancel()
            self.handle.pending_user_inputs.pop(tool_call_id, None)

    async def _handle_enter_plan_mode(self, tool_call_id: str) -> ToolResult:
        mode = (self.mode or "agent").strip() or "agent"
        if mode == "plan":
            return ToolResult(
                content="Already in plan mode. Continue investigating, then "
                "call update_plan and exit_plan_mode when ready.",
                success=True,
            )
        response = await self._await_user_input_raw(
            tool_call_id,
            enter_plan_questions(getattr(self, "reply_locale", None)),
            purpose=ENTER_PLAN_MODE_NAME,
        )
        if response is None:
            return ToolResult(
                content="Enter plan mode cancelled (turn cancelled).",
                success=False,
            )
        err = response.get("error")
        if isinstance(err, str) and err.strip():
            return ToolResult(content=err.strip(), success=False)
        if response.get("cancelled"):
            return ToolResult(
                content="User dismissed enter_plan_mode. Staying in "
                f"{mode} mode — continue without planning gate.",
                success=False,
            )
        approved = parse_enter_plan_response(response)
        if approved is None:
            return ToolResult(
                content="User dismissed enter_plan_mode. Staying in "
                f"{mode} mode — continue without planning gate.",
                success=False,
            )
        if not approved:
            return ToolResult(
                content="User declined plan mode. Continue in the current "
                "mode; keep changes small or ask again if the scope grows.",
                success=False,
            )

        self._set_approved_plan(False)
        await self.apply_interaction_mode("plan", reason="enter_plan_mode")
        return ToolResult(
            content=(
                "Entered plan mode (read-only). Investigate the codebase, "
                "clarify with request_user_input if needed, write the plan "
                "via update_plan, then call exit_plan_mode for approval. "
                "Do not edit files or run shell until the plan is accepted."
            ),
            success=True,
            metadata={"mode": "plan"},
        )

    async def _handle_exit_plan_mode(self, tool_call_id: str) -> ToolResult:
        mode = (self.mode or "agent").strip() or "agent"
        if mode != "plan":
            return ToolResult(
                content="Not in plan mode. Call enter_plan_mode first "
                "(or have the user switch to plan) before exit_plan_mode.",
                success=False,
            )
        if not plan_file_exists(self.tool_context.working_directory, self.tool_context.metadata):
            return ToolResult(
                content="No plan found. Call update_plan with the full plan before exit_plan_mode.",
                success=False,
            )

        response = await self._await_user_input_raw(
            tool_call_id,
            exit_plan_questions(getattr(self, "reply_locale", None)),
            purpose=EXIT_PLAN_MODE_NAME,
        )
        if response is None:
            return ToolResult(
                content="Exit plan mode cancelled (turn cancelled).",
                success=False,
            )
        err = response.get("error")
        if isinstance(err, str) and err.strip():
            return ToolResult(content=err.strip(), success=False)
        if response.get("cancelled"):
            return ToolResult(
                content="User dismissed plan approval. Staying in plan mode "
                "— revise with update_plan or call exit_plan_mode again.",
                success=False,
            )
        outcome = parse_exit_plan_response(response)
        if outcome is None:
            return ToolResult(
                content="User dismissed plan approval. Staying in plan mode "
                "— revise with update_plan or call exit_plan_mode again.",
                success=False,
            )
        if outcome == EXIT_REVISE:
            self._stop_after_exit_plan = False
            return ToolResult(
                content="User asked to revise the plan. Stay in plan mode, "
                "update the plan, then call exit_plan_mode again.",
                success=False,
                metadata={"outcome": outcome},
            )
        if outcome == EXIT_ACCEPT_YOLO:
            self._stop_after_exit_plan = False
            self._set_approved_plan(True)
            await self.apply_interaction_mode("yolo", reason="exit_plan_mode")
            return ToolResult(
                content="Plan accepted (YOLO). Implement the plan now with "
                "auto-approved tool calls.",
                success=True,
                metadata={"outcome": outcome, "mode": "yolo"},
            )
        if outcome == EXIT_LEAVE:
            self._set_approved_plan(False)
            await self.apply_interaction_mode("agent", reason="exit_plan_mode")
            self._stop_after_exit_plan = True
            return ToolResult(
                content="Left plan mode without starting implementation. "
                "Wait for the user's next instruction.",
                success=True,
                metadata={"outcome": outcome, "mode": "agent"},
            )
        # Default: accept in agent mode
        self._stop_after_exit_plan = False
        self._set_approved_plan(True)
        await self.apply_interaction_mode("agent", reason="exit_plan_mode")
        return ToolResult(
            content="Plan accepted (Agent). Implement the plan now, "
            "requesting approvals for writes as usual.",
            success=True,
            metadata={"outcome": outcome or EXIT_ACCEPT_AGENT, "mode": "agent"},
        )

    def _set_approved_plan(self, approved: bool) -> None:
        self.tool_context.metadata["approved_plan"] = bool(approved)

    async def apply_interaction_mode(self, mode: str, *, reason: str = "") -> None:
        """Switch interaction mode and notify listeners.

        Rebuilds a private registry when this engine owns its tool runtime.
        Shared registries stay intact — plan restrictions are enforced via
        ``PLAN_MODE_TOOL_ALLOWLIST`` filtering instead.
        """
        previous = (self.mode or "agent").strip() or "agent"
        next_mode = (mode or "agent").strip() or "agent"
        if previous == next_mode:
            return
        self.mode = next_mode
        if next_mode == "plan":
            self._set_approved_plan(False)
        elif previous == "plan" and reason != "exit_plan_mode":
            self._set_approved_plan(False)
        try:
            from deepseek_tui.policy.sandbox import sync_execution_sandbox_policy

            sync_execution_sandbox_policy(
                self.tool_context,
                next_mode,
                self.tool_context.working_directory,
            )
        except Exception:  # noqa: BLE001 — mode switch must not fail the tool
            logger.debug("sync_execution_sandbox_policy_failed", exc_info=True)

        if next_mode == "yolo":
            from deepseek_tui.engine.handle import AutoApprovalHandler

            self.approval_handler = AutoApprovalHandler()

        if getattr(self, "_owns_tool_runtime", False):
            cfg = getattr(self, "_app_config", None)
            if cfg is not None:
                try:
                    from deepseek_tui.tools.registry import build_default_registry

                    new_registry = build_default_registry(cfg, mode=next_mode)
                    new_registry.set_context(self.tool_context)
                    self.tool_registry = new_registry
                    if self.tool_runtime is not None:
                        self.tool_runtime.registry = new_registry
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "rebuild_registry_for_mode_failed mode=%s",
                        next_mode,
                        exc_info=True,
                    )

        await self.handle.emit(
            ModeChangedEvent(
                mode=next_mode,
                previous_mode=previous,
                reason=reason,
            )
        )
