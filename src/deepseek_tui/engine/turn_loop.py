"""Main streaming turn loop for the engine.

Mirrors `crates/tui/src/core/engine/turn_loop.rs:1-1597`
"""

from __future__ import annotations

import asyncio
import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.context import context_input_budget, estimated_input_tokens
from deepseek_tui.engine.events import (
    EngineEvent,
    ErrorEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
)
from deepseek_tui.engine.streaming import AssistantResponseBuffer
from deepseek_tui.engine.tool_catalog import (
    active_tools_for_step,
    ensure_advanced_tooling,
    initial_active_tools,
)
from deepseek_tui.engine.tool_parser import has_tool_call_markers, parse_tool_calls
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
    ToolCall,
    Usage,
)

# Mirrors Rust constants from turn_loop.rs
MAX_STREAM_RETRIES = 3
MAX_CONTEXT_RECOVERY_ATTEMPTS = 3
TURN_MAX_OUTPUT_TOKENS = 16384


class TurnOutcomeStatus(enum.Enum):
    """Mirrors Rust TurnOutcomeStatus enum."""
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CONTEXT_OVERFLOW = "context_overflow"


@dataclass(frozen=True, slots=True)
class TurnResult:
    """Result of a single turn execution."""
    assistant_message: Message | None
    usage: Usage | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    cancelled: bool = False
    outcome: TurnOutcomeStatus = TurnOutcomeStatus.SUCCESS
    error_message: str | None = None


@dataclass
class _TurnState:
    """Internal turn state tracking (mirrors Rust state variables)."""
    consecutive_tool_error_steps: int = 0
    context_recovery_attempts: int = 0
    stream_retry_attempts: int = 0
    active_tool_names: set[str] = field(default_factory=set)
    turn_error: str | None = None


class TurnLoop:
    """Main streaming turn loop orchestrator.

    Mirrors `Engine::handle_deepseek_turn` from Rust.
    """
    def __init__(
        self,
        client: LLMClient,
        compact_fn: Callable[[list[Message]], Awaitable[list[Message]]] | None = None,
    ) -> None:
        self.client = client
        self._compact_fn = compact_fn

    async def run(
        self,
        request: MessageRequest,
        emit: Callable[[EngineEvent], Awaitable[None]],
        cancel_event: asyncio.Event,
        tools: list[dict[str, Any]] | None = None,
    ) -> TurnResult:
        """Run a single turn of the conversation loop.

        Args:
            request: Message request to send
            emit: Callback to emit engine events
            cancel_event: Cancellation event
            tools: Optional tool catalog

        Returns:
            TurnResult with outcome and extracted data
        """
        state = _TurnState()
        tool_catalog = tools or []

        if tool_catalog:
            ensure_advanced_tooling(tool_catalog)

        state.active_tool_names = initial_active_tools(tool_catalog)

        # Main streaming turn loop
        result = await self._run_turn_loop(
            request=request,
            emit=emit,
            cancel_event=cancel_event,
            tool_catalog=tool_catalog,
            state=state,
        )

        return result

    async def _run_turn_loop(
        self,
        request: MessageRequest,
        emit: Callable[[EngineEvent], Awaitable[None]],
        cancel_event: asyncio.Event,
        tool_catalog: list[dict[str, Any]],
        state: _TurnState,
    ) -> TurnResult:
        """Core turn loop logic (mirrors Rust handle_deepseek_turn main loop)."""
        buffer = AssistantResponseBuffer()
        usage: Usage | None = None
        tool_calls: list[ToolCall] = []

        # Stream retry loop (for transparent retries on mid-stream failures)
        while state.stream_retry_attempts < MAX_STREAM_RETRIES:
            if cancel_event.is_set():
                return TurnResult(
                    assistant_message=buffer.build_message(),
                    usage=usage,
                    tool_calls=tool_calls,
                    cancelled=True,
                    outcome=TurnOutcomeStatus.INTERRUPTED,
                )

            # Check context budget before requesting
            if request.messages:
                input_budget = context_input_budget(request.model, TURN_MAX_OUTPUT_TOKENS)
                if input_budget is not None:
                    estimated_input = estimated_input_tokens(request.messages)
                    if estimated_input > input_budget:
                        if state.context_recovery_attempts >= MAX_CONTEXT_RECOVERY_ATTEMPTS:
                            msg = (
                                f"Context remains above model limit after "
                                f"{MAX_CONTEXT_RECOVERY_ATTEMPTS} recovery attempts "
                                f"(~{estimated_input} token estimate, ~{input_budget} budget). "
                                f"Please run /compact or /clear."
                            )
                            await emit(ErrorEvent(message=msg, retryable=False))
                            return TurnResult(
                                assistant_message=None,
                                usage=None,
                                cancelled=False,
                                outcome=TurnOutcomeStatus.CONTEXT_OVERFLOW,
                                error_message=msg,
                            )
                        state.context_recovery_attempts += 1
                        # Emergency compaction — mirrors turn_loop.rs:177-208
                        if self._compact_fn is not None:
                            request.messages[:] = await self._compact_fn(
                                request.messages
                            )
                        continue

            # Build request with active tools
            active_tools = None
            if tool_catalog:
                active_tools = active_tools_for_step(
                    tool_catalog,
                    state.active_tool_names,
                    force_update_plan_first=False,
                )

            stream_request = MessageRequest(
                model=request.model,
                messages=request.messages,
                system_prompt=request.system_prompt,
                tools=active_tools or [],
                tool_choice={"type": "auto"} if active_tools else None,
                max_tokens=TURN_MAX_OUTPUT_TOKENS,
                stream=True,
            )

            # Attempt to stream response
            try:
                async for stream_event in self.client.stream_with_retry(stream_request):
                    if cancel_event.is_set():
                        return TurnResult(
                            assistant_message=buffer.build_message(),
                            usage=usage,
                            tool_calls=tool_calls,
                            cancelled=True,
                            outcome=TurnOutcomeStatus.INTERRUPTED,
                        )

                    if isinstance(stream_event, StreamTextDelta):
                        buffer.append_text(stream_event.text)
                        await emit(TextDeltaEvent(text=stream_event.text))
                    elif isinstance(stream_event, StreamThinkingDelta):
                        buffer.append_thinking(stream_event.thinking)
                        await emit(ThinkingDeltaEvent(thinking=stream_event.thinking))
                    elif isinstance(stream_event, StreamToolCallComplete):
                        tool_calls.append(stream_event.tool_call)
                        await emit(ToolCallEvent(tool_call=stream_event.tool_call))
                    elif isinstance(stream_event, StreamError):
                        await emit(
                            ErrorEvent(
                                message=stream_event.message,
                                retryable=stream_event.retryable,
                            )
                        )
                    elif isinstance(stream_event, StreamDone):
                        usage = stream_event.usage

                # Text-based tool call fallback (DeepSeek models may emit
                # tool calls as text rather than structured blocks).
                # Mirrors turn_loop.rs:726-758.
                accumulated_text = "".join(buffer.text_parts)
                if not tool_calls and accumulated_text:
                    if has_tool_call_markers(accumulated_text):
                        parsed = parse_tool_calls(accumulated_text)
                        for tc in parsed.tool_calls:
                            converted = ToolCall(
                                id=tc.id,
                                name=tc.name,
                                arguments=dict(tc.args) if tc.args else {},
                            )
                            tool_calls.append(converted)
                            await emit(ToolCallEvent(tool_call=converted))
                        buffer.text_parts[:] = [parsed.clean_text]

                # Stream completed successfully
                state.context_recovery_attempts = 0
                break

            except Exception as e:
                # Stream failed, potentially retryable
                err_msg = str(e)
                state.stream_retry_attempts += 1

                if state.stream_retry_attempts < MAX_STREAM_RETRIES:
                    # Retry transparently
                    await emit(
                        ErrorEvent(
                            message="Stream interrupted, retrying...", retryable=True
                        )
                    )
                    continue
                else:
                    # Max retries exceeded
                    await emit(ErrorEvent(message=err_msg, retryable=False))
                    return TurnResult(
                        assistant_message=None,
                        usage=usage,
                        cancelled=False,
                        outcome=TurnOutcomeStatus.FAILED,
                        error_message=err_msg,
                    )

        return TurnResult(
            assistant_message=buffer.build_message(),
            usage=usage,
            tool_calls=tool_calls,
            cancelled=False,
            outcome=TurnOutcomeStatus.SUCCESS,
        )
