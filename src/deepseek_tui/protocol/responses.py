

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class Usage(BaseModel):
    """Token-usage accounting for a single LLM response.

    Mirrors Rust ``crates/tui/src/models.rs::Usage`` (185-202). DeepSeek
    returns ``prompt_tokens`` / ``completion_tokens`` and provides
    ``prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens`` and
    ``completion_tokens_details.reasoning_tokens``. We accept those wire
    names via Pydantic v2 ``AliasChoices`` so ``Usage.model_validate``
    on a raw API payload no longer silently drops cache/reasoning counts.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    input_tokens: int = Field(
        default=0,
        validation_alias=AliasChoices("input_tokens", "prompt_tokens"),
    )
    output_tokens: int = Field(
        default=0,
        validation_alias=AliasChoices("output_tokens", "completion_tokens"),
    )
    cache_creation_input_tokens: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "cache_creation_input_tokens", "prompt_cache_miss_tokens"
        ),
    )
    cache_read_input_tokens: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "cache_read_input_tokens", "prompt_cache_hit_tokens"
        ),
    )
    reasoning_tokens: int = 0

    @model_validator(mode="before")
    @classmethod
    def _extract_nested_reasoning(cls, data: Any) -> Any:
        """Pull reasoning_tokens out of completion_tokens_details if present.

        DeepSeek puts it nested under ``completion_tokens_details``; Rust
        ``parse_usage`` handles this same path. Avoid clobbering an explicit
        top-level ``reasoning_tokens`` if the caller already set one.
        """
        if not isinstance(data, dict):
            return data
        if "reasoning_tokens" in data and data["reasoning_tokens"]:
            return data
        details = data.get("completion_tokens_details")
        if isinstance(details, dict):
            nested = details.get("reasoning_tokens")
            if isinstance(nested, int):
                data = {**data, "reasoning_tokens": nested}
        return data


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
