from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.events import (
    EngineEvent,
    ErrorEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
)
from deepseek_tui.engine.streaming import AssistantResponseBuffer
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


@dataclass(frozen=True, slots=True)
class TurnResult:
    assistant_message: Message | None
    usage: Usage | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    cancelled: bool = False


class TurnLoop:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    async def run(
        self,
        request: MessageRequest,
        emit: Callable[[EngineEvent], Awaitable[None]],
        cancel_event: asyncio.Event,
    ) -> TurnResult:
        buffer = AssistantResponseBuffer()
        usage: Usage | None = None
        tool_calls: list[ToolCall] = []

        async for stream_event in self.client.stream_with_retry(request):
            if cancel_event.is_set():
                return TurnResult(
                    assistant_message=buffer.build_message(),
                    usage=usage,
                    tool_calls=tool_calls,
                    cancelled=True,
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

        return TurnResult(
            assistant_message=buffer.build_message(),
            usage=usage,
            tool_calls=tool_calls,
        )
