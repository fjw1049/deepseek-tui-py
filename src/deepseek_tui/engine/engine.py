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
from deepseek_tui.execpolicy.engine import ExecPolicyEngine
from deepseek_tui.execpolicy.models import ApprovalDecision
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
        for _ in range(self.max_tool_round_trips + 1):
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
                            in {ApprovalDecision.APPROVED, ApprovalDecision.APPROVED_SESSION},
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
                        results.append(Message.tool_result(tool_call.id, reason, is_error=True))
                        continue
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
