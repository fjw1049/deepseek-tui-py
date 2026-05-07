from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.approval import ApprovalHandler, AutoApprovalHandler
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ErrorEvent,
    SandboxDeniedEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.ops import CancelRequestOp, SendMessageOp
from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.engine.turn_loop import TurnLoop, TurnResult
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
from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from deepseek_tui.tools.runtime import ToolRuntime


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
        max_tool_round_trips: int = 3,
        tool_runtime: ToolRuntime | None = None,
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
        self.session_messages: list[Message] = []
        self.turn_loop = TurnLoop(client)
        # Stage 4.4 post-edit LSP diagnostics — Rust ``Engine.pending_lsp_blocks``
        self.pending_lsp_blocks: list[DiagnosticBlock] = []
        self.turn_counter = 0
        # Stage 3.next.1 approval cache — fingerprints repeat tool calls
        # so an APPROVED_SESSION grant doesn't have to re-prompt.
        self.approval_cache = ApprovalCache()

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
        max_tool_round_trips: int = 3,
    ) -> Engine:
        """Construct an Engine with a freshly-wired :class:`ToolRuntime`.

        This is the integration-complete path: all managers (task/subagent),
        the full registry, and the ToolContext are created together so that
        tools can actually reach the managers at dispatch time.
        """
        from deepseek_tui.config.models import Config
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = config if isinstance(config, Config) else Config()
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=working_directory,
            mode=mode,
        )
        return cls(
            handle=handle,
            client=client,
            default_model=default_model,
            exec_policy=exec_policy,
            approval_handler=approval_handler,
            max_tool_round_trips=max_tool_round_trips,
            tool_runtime=runtime,
        )

    async def shutdown(self) -> None:
        """Drain managers owned by the tool runtime if Engine built it."""
        if self.tool_runtime is not None:
            await self.tool_runtime.shutdown()

    async def run(self) -> None:
        while True:
            op = await self.handle.next_op()
            if isinstance(op, SendMessageOp):
                await self._handle_send_message(op)
            elif isinstance(op, CancelRequestOp):
                continue

    async def _handle_send_message(self, op: SendMessageOp) -> None:
        self.handle.reset_cancel()
        user_message = Message.user(op.content)
        working_messages = [*self.session_messages, user_message]

        await self.handle.emit(TurnStartedEvent(user_text=op.content))
        result = await self._run_conversation(
            messages=working_messages,
            model=op.model or self.default_model,
            system_prompt=build_system_prompt(op.system_prompt),
            max_tokens=op.max_tokens,
        )

        if result.cancelled:
            await self.handle.emit(TurnCancelledEvent(reason="user_cancelled"))
            return

        self.session_messages = working_messages
        await self.handle.emit(
            TurnCompleteEvent(
                assistant_message=result.assistant_message,
                usage=result.usage,
            )
        )

    async def _run_conversation(
        self,
        messages: list[Message],
        model: str,
        system_prompt: str,
        max_tokens: int | None,
    ) -> TurnResult:
        tools = self.tool_registry.to_api_tools()
        self.turn_counter += 1
        for _ in range(self.max_tool_round_trips + 1):
            # Flush any diagnostics queued by post-edit hooks from the
            # previous round-trip so the model sees them on this request.
            self._flush_pending_lsp_diagnostics(messages)
            request = MessageRequest(
                model=model,
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                max_tokens=max_tokens,
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
            messages.extend(await self._execute_tool_calls(result.tool_calls))

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

    async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[Message]:
        results: list[Message] = []
        for tool_call in tool_calls:
            try:
                tool = self.tool_registry.get(tool_call.name)
                approval_request = self.exec_policy.evaluate(tool_call.name, tool.capabilities())
                if approval_request is not None:
                    # Stage 3.next.1: check fingerprint cache first.
                    # APPROVED → skip handler entirely (silent reuse).
                    # DENIED   → grant was one-shot and consumed; fall
                    #            through to handler.
                    # UNKNOWN  → no prior decision; fall through to handler.
                    cache_key = build_approval_key(
                        tool_call.name, tool_call.arguments
                    )
                    cache_status = self.approval_cache.check(cache_key)
                    if cache_status is ApprovalCacheStatus.APPROVED:
                        await self.handle.emit(
                            ApprovalResolvedEvent(
                                tool_call_id=tool_call.id,
                                approved=True,
                                reason="cached_session",
                            )
                        )
                    else:
                        await self.handle.emit(
                            ApprovalRequiredEvent(
                                tool_call_id=tool_call.id,
                                request=approval_request,
                            )
                        )
                        decision = await self.approval_handler.request_approval(
                            tool_call.id,
                            approval_request,
                        )
                        await self.handle.emit(
                            ApprovalResolvedEvent(
                                tool_call_id=tool_call.id,
                                approved=decision
                                in {
                                    ApprovalDecision.APPROVED,
                                    ApprovalDecision.APPROVED_SESSION,
                                },
                                reason=decision.value,
                            )
                        )
                        if decision is ApprovalDecision.DENIED:
                            reason = f"Tool {tool_call.name} denied by approval policy"
                            await self.handle.emit(
                                SandboxDeniedEvent(
                                    tool_call_id=tool_call.id,
                                    tool_name=tool_call.name,
                                    reason=reason,
                                )
                            )
                            results.append(
                                Message.tool_result(
                                    tool_call.id, reason, is_error=True
                                )
                            )
                            continue
                        # Persist the grant so repeat calls match.
                        self.approval_cache.insert(
                            cache_key,
                            approved_for_session=(
                                decision is ApprovalDecision.APPROVED_SESSION
                            ),
                        )
                        self.exec_policy.record_decision(tool_call.name, decision)
                result = await self.tool_registry.execute(
                    tool_call.name,
                    tool_call.arguments,
                    self.tool_context,
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
                results.append(
                    Message.tool_result(
                        tool_call.id,
                        result.content,
                        is_error=not result.success,
                    )
                )
            except ToolError as exc:
                await self.handle.emit(ErrorEvent(message=str(exc), retryable=False))
                results.append(Message.tool_result(tool_call.id, str(exc), is_error=True))
        return results

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
