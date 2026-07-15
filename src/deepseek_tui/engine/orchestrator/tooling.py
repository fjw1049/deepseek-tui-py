"""Tool-execution half of the Engine (mixin).

Sequential + parallel tool dispatch, approval/elevation flow, tool_search
activation, and interactive user-input waits.
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
    parse_parallel_tool_calls,
    should_parallelize_tool_batch,
)
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ElevationRequiredEvent,
    SandboxDeniedEvent,
    ToolResultEvent,
    UserInputRequiredEvent,
    WorkflowProgressEvent,
)
from deepseek_tui.engine.tools import (
    CODE_EXECUTION_TOOL_NAME,
    MULTI_TOOL_PARALLEL_NAME,
    REQUEST_USER_INPUT_NAME,
    execute_code_execution_tool,
    execute_tool_search,
    is_tool_search_tool,
    maybe_activate_requested_deferred_tool,
    missing_tool_error_message,
)
from deepseek_tui.policy.approval import (
    ApprovalCacheStatus,
    ApprovalDecision,
    build_approval_key,
)
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolError, ToolResult
from deepseek_tui.utils import bind_tool

logger = logging.getLogger(__name__)


class ToolExecutionMixin:
    """Tool dispatch / approval / elevation methods shared into Engine."""

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

    def _mcp_declared_capabilities(self, tool_name: str) -> list[str]:
        """Capability hints declared for an MCP tool's server (plugin
        manifest ``permissions``); empty when unknown / undeclared."""
        if self.mcp_manager is None:
            return []
        return self.mcp_manager.declared_capabilities(tool_name)

    async def _execute_tool_calls(
        self, tool_calls: list[ToolCall], model: str | None = None
    ) -> list[Message]:
        results: list[Message] = []
        effective_model = model or self.default_model
        api_tools = await self._get_tools_with_mcp()

        # Build execution plans and check if batch can be parallelized
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
                        approval_required=plan_requires_mcp_approval(
                            tc.name,
                            policy,
                            self._mcp_declared_capabilities(tc.name),
                        ),
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

        # 先归一化：把桥接别名（如 mcp_read_resource）映射回注册表工具名，
        # 后续的 is_external_mcp_tool 判定才会把它正确归到注册表分支而非外部 MCP 分支。
        tool_name = normalize_mcp_bridge_tool_name(tool_call.name)
        # 写文件类工具执行前拍快照（供 /undo）。注意：parallel 自身不是写工具，
        # 这里不会拍；其子工具的快照由 _execute_parallel_tools 逐个走完整分发时各自拍。
        self._take_pre_tool_snapshot(tool_call.id, tool_name, tool_call.arguments)

        # --- Special built-in tools (not in ToolRegistry) ---
        if is_tool_search_tool(tool_name):
            # Discovered tools land in the session-level activation set so
            # they stay advertised on subsequent rounds/turns.
            return execute_tool_search(
                tool_name, tool_call.arguments, api_tools,
                self._activated_tool_names,
            )

        # A direct call to a deferred tool activates it for later rounds.
        maybe_activate_requested_deferred_tool(
            tool_name, api_tools, self._activated_tool_names
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
                tool_name,
                self.exec_policy.approval_policy,
                self._mcp_declared_capabilities(tool_name),
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

    async def _execute_parallel_tools(self, input_data: dict[str, Any]) -> ToolResult:
        """Fan out multi_tool_use.parallel sub-calls concurrently.

        Only read-only tools that don't require approval are eligible.
        Recursive self-calls are rejected.
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
            # Align with batch parallelization: tools that need an approval
            # prompt (or never-block) must not bypass _execute_single_tool.
            from deepseek_tui.tools.approval import plan_requires_approval

            if plan_requires_approval(tool, self.exec_policy.approval_policy):
                return {
                    "tool": name,
                    "error": (
                        f"Tool '{name}' requires approval and cannot run "
                        "inside multi_tool_use.parallel; call it directly"
                    ),
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
