from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class StreamEventType(str, Enum):
    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    ERROR = "error"
    DONE = "done"


class StreamTextDelta(BaseModel):
    type: Literal[StreamEventType.TEXT_DELTA] = StreamEventType.TEXT_DELTA
    text: str


class StreamThinkingDelta(BaseModel):
    type: Literal[StreamEventType.THINKING_DELTA] = StreamEventType.THINKING_DELTA
    thinking: str


class StreamToolCallDelta(BaseModel):
    type: Literal[StreamEventType.TOOL_CALL_DELTA] = StreamEventType.TOOL_CALL_DELTA
    tool_call_id: str
    name: str | None = None
    arguments_fragment: str = ""


class StreamToolCallComplete(BaseModel):
    type: Literal[StreamEventType.TOOL_CALL_COMPLETE] = StreamEventType.TOOL_CALL_COMPLETE
    tool_call: ToolCall


class StreamError(BaseModel):
    type: Literal[StreamEventType.ERROR] = StreamEventType.ERROR
    message: str
    retryable: bool = False


class StreamDone(BaseModel):
    type: Literal[StreamEventType.DONE] = StreamEventType.DONE
    usage: Usage | None = None


StreamEvent = Annotated[
    StreamTextDelta
    | StreamThinkingDelta
    | StreamToolCallDelta
    | StreamToolCallComplete
    | StreamError
    | StreamDone,
    Field(discriminator="type"),
]
