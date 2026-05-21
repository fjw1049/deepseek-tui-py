"""Main streaming turn loop for the engine.

Mirrors `crates/tui/src/core/engine/turn_loop.rs:1-1597`
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
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
from deepseek_tui.engine.streaming import (
    FAKE_WRAPPER_NOTICE,
    AssistantResponseBuffer,
    FakeWrapperFilter,
    contains_fake_tool_wrapper,
)
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
    StreamToolCallDelta,
    ToolCall,
    Usage,
)

logger = logging.getLogger(__name__)

# Mirrors Rust constants from streaming.rs / turn_loop.rs
MAX_STREAM_RETRIES = 3
MAX_CONTEXT_RECOVERY_ATTEMPTS = 3
TURN_MAX_OUTPUT_TOKENS = 262_144

# Stream guard constants (mirrors Rust streaming.rs)
STREAM_CHUNK_TIMEOUT_SECS = 90
STREAM_MAX_DURATION_SECS = 1800
STREAM_MAX_CONTENT_BYTES = 10 * 1024 * 1024
MAX_TRANSPARENT_STREAM_RETRIES = 2


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
        # 延迟加载，模型至少能直接调用代码执行和工具发现能力，其余工具按延迟加载策略按需激活
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
        logger.info(
            "stream_start model=%s msg_count=%d tools_count=%d "
            "max_tokens=%s reasoning_effort=%s",
            request.model,
            len(request.messages),
            len(tool_catalog),
            request.max_tokens,
            request.reasoning_effort,
        )

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
                        logger.warning(
                            "context_overflow estimated=%d budget=%d attempts=%d",
                            estimated_input,
                            input_budget,
                            state.context_recovery_attempts,
                        )
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
                        if self._compact_fn is not None:
                            request.messages[:] = await self._compact_fn(
                                request.messages
                            )
                        continue

            # Build request with active tools
            # 重建 stream 请求 — 只发「当前激活」的工具
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
                tool_choice=(
                    request.tool_choice
                    if request.tool_choice is not None
                    else ({"type": "auto"} if active_tools else None)
                ),
                max_tokens=request.max_tokens or TURN_MAX_OUTPUT_TOKENS,
                # Forward reasoning / sampling controls from the upstream
                # request so non-streaming Engine config (Config.reasoning_effort
                # etc.) reaches the LLM client. Without this propagation the
                # rebuilt request below would silently drop these fields and
                # reasoning models (DeepSeek-R1 / V4) would never enable
                # thinking. Mirrors Rust turn_loop.rs which preserves them.
                temperature=request.temperature,
                top_p=request.top_p,
                reasoning_effort=request.reasoning_effort,
                extra_body=dict(request.extra_body),
                stream=True,
            )

            # Attempt to stream response with timeout guards
            try:
                any_content_received = False
                transparent_retries = 0
                stream_start = time.monotonic()
                content_bytes = 0
                fake_filter = FakeWrapperFilter()
                fake_notice_sent = False

                async for stream_event in self.client.stream_with_retry(stream_request):
                    if cancel_event.is_set():
                        return TurnResult(
                            assistant_message=buffer.build_message(),
                            usage=usage,
                            tool_calls=tool_calls,
                            cancelled=True,
                            outcome=TurnOutcomeStatus.INTERRUPTED,
                        )

                    # Wall-clock duration guard (30 min)
                    elapsed = time.monotonic() - stream_start
                    if elapsed > STREAM_MAX_DURATION_SECS:
                        msg = f"Stream exceeded max duration ({STREAM_MAX_DURATION_SECS}s)"
                        logger.warning(
                            "stream_wall_clock_exceeded elapsed=%.1fs threshold=%ds",
                            elapsed,
                            STREAM_MAX_DURATION_SECS,
                        )
                        await emit(ErrorEvent(message=msg, retryable=False))
                        return TurnResult(
                            assistant_message=buffer.build_message(),
                            usage=usage,
                            tool_calls=tool_calls,
                            cancelled=False,
                            outcome=TurnOutcomeStatus.FAILED,
                            error_message=msg,
                        )

                    if isinstance(stream_event, StreamTextDelta):
                        any_content_received = True
                        raw = stream_event.text
                        # Buffer keeps RAW text so the post-stream tool_parser
                        # fallback can still detect markers. Only the visible
                        # delta is scrubbed of fake wrappers (mirrors Rust:
                        # buffer holds canonical, emit shows cleaned UX).
                        buffer.append_text(raw)
                        if (
                            not fake_notice_sent
                            and (fake_filter.in_tool_call or contains_fake_tool_wrapper(raw))
                        ):
                            fake_notice_sent = True
                            logger.info("fake_wrapper_detected: %s", FAKE_WRAPPER_NOTICE)
                        cleaned = fake_filter.filter(raw)
                        content_bytes += len(cleaned.encode())
                        if cleaned:
                            logger.debug(
                                "sse_chunk type=text_delta bytes=%d", len(cleaned)
                            )
                            await emit(TextDeltaEvent(text=cleaned))
                    elif isinstance(stream_event, StreamThinkingDelta):
                        any_content_received = True
                        content_bytes += len(stream_event.thinking.encode())
                        logger.debug(
                            "sse_chunk type=thinking_delta bytes=%d",
                            len(stream_event.thinking),
                        )
                        buffer.append_thinking(stream_event.thinking)
                        await emit(ThinkingDeltaEvent(thinking=stream_event.thinking))
                    elif isinstance(stream_event, StreamToolCallDelta):
                        any_content_received = True
                        content_bytes += len(
                            stream_event.arguments_fragment.encode()
                        )
                        logger.debug(
                            "sse_chunk type=tool_call_delta bytes=%d",
                            len(stream_event.arguments_fragment),
                        )
                    elif isinstance(stream_event, StreamToolCallComplete):
                        any_content_received = True
                        tool_calls.append(stream_event.tool_call)
                        logger.info(
                            "tool_call_received name=%s id=%s",
                            stream_event.tool_call.name,
                            stream_event.tool_call.id[:8],
                        )
                        await emit(ToolCallEvent(tool_call=stream_event.tool_call))
                    elif isinstance(stream_event, StreamError):
                        # Transparent retry: only if no content received yet
                        if _should_transparently_retry(
                            any_content_received, transparent_retries, cancel_event.is_set()
                        ):
                            transparent_retries += 1
                            logger.warning(
                                "stream_transparent_retry attempt=%d/%d reason=%s",
                                transparent_retries,
                                MAX_TRANSPARENT_STREAM_RETRIES,
                                stream_event.message,
                            )
                            break  # break inner loop to retry
                        logger.warning(
                            "stream_error_emit message=%s retryable=%s",
                            stream_event.message,
                            stream_event.retryable,
                        )
                        await emit(
                            ErrorEvent(
                                message=stream_event.message,
                                retryable=stream_event.retryable,
                            )
                        )
                    elif isinstance(stream_event, StreamDone):
                        usage = stream_event.usage
                        logger.info(
                            "stream_done duration_ms=%d input_tokens=%s "
                            "output_tokens=%s reasoning_tokens=%s",
                            int((time.monotonic() - stream_start) * 1000),
                            getattr(usage, "input_tokens", 0) if usage else 0,
                            getattr(usage, "output_tokens", 0) if usage else 0,
                            getattr(usage, "reasoning_tokens", 0) if usage else 0,
                        )

                    # Content byte guard (10 MB)
                    if content_bytes > STREAM_MAX_CONTENT_BYTES:
                        msg = f"Stream content exceeded {STREAM_MAX_CONTENT_BYTES} bytes"
                        logger.warning(
                            "stream_content_exceeded bytes=%d threshold=%d",
                            content_bytes,
                            STREAM_MAX_CONTENT_BYTES,
                        )
                        await emit(ErrorEvent(message=msg, retryable=False))
                        return TurnResult(
                            assistant_message=buffer.build_message(),
                            usage=usage,
                            tool_calls=tool_calls,
                            cancelled=False,
                            outcome=TurnOutcomeStatus.FAILED,
                            error_message=msg,
                        )
                else:
                    # Stream completed normally (for-else: no break)
                    # Text-based tool call fallback
                    accumulated_text = "".join(buffer.text_parts)
                    if not tool_calls and accumulated_text:
                        if has_tool_call_markers(accumulated_text):
                            parsed = parse_tool_calls(accumulated_text)
                            logger.info(
                                "tool_parser_fallback tool_calls=%d clean_chars=%d",
                                len(parsed.tool_calls),
                                len(parsed.clean_text),
                            )
                            for tc in parsed.tool_calls:
                                converted = ToolCall(
                                    id=tc.id,
                                    name=tc.name,
                                    arguments=dict(tc.args) if tc.args else {},
                                )
                                tool_calls.append(converted)
                                await emit(ToolCallEvent(tool_call=converted))
                            buffer.text_parts[:] = [parsed.clean_text]

                    state.context_recovery_attempts = 0
                    break  # success — exit retry loop

                # If we broke out of the for loop (transparent retry), continue
                continue

            except asyncio.TimeoutError:
                msg = f"Stream chunk timeout ({STREAM_CHUNK_TIMEOUT_SECS}s idle)"
                logger.warning(
                    "stream_chunk_timeout idle_threshold=%ds attempts=%d",
                    STREAM_CHUNK_TIMEOUT_SECS,
                    state.stream_retry_attempts,
                )
                if _should_transparently_retry(
                    any_content_received, state.stream_retry_attempts, cancel_event.is_set()
                ):
                    state.stream_retry_attempts += 1
                    logger.info(
                        "stream_timeout_retry attempt=%d/%d",
                        state.stream_retry_attempts, MAX_STREAM_RETRIES,
                    )
                    continue
                await emit(ErrorEvent(message=msg, retryable=False))
                return TurnResult(
                    assistant_message=buffer.build_message(),
                    usage=usage,
                    tool_calls=tool_calls,
                    cancelled=False,
                    outcome=TurnOutcomeStatus.FAILED,
                    error_message=msg,
                )

            except Exception as e:
                err_msg = str(e)
                state.stream_retry_attempts += 1

                if _should_transparently_retry(
                    any_content_received, state.stream_retry_attempts, cancel_event.is_set()
                ):
                    logger.info(
                        "Stream error, transparent retry %d/%d: %s",
                        state.stream_retry_attempts, MAX_STREAM_RETRIES, err_msg,
                    )
                    continue
                elif state.stream_retry_attempts < MAX_STREAM_RETRIES:
                    await emit(
                        ErrorEvent(message="Stream interrupted, retrying...", retryable=True)
                    )
                    continue
                else:
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


def _should_transparently_retry(
    any_content_received: bool, attempts: int, cancelled: bool
) -> bool:
    """Mirrors Rust should_transparently_retry_stream()."""
    return (
        not any_content_received
        and attempts < MAX_TRANSPARENT_STREAM_RETRIES
        and not cancelled
    )
