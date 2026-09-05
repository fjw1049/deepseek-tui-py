from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class Usage(BaseModel):
    """Token-usage accounting for a single LLM response.

    DeepSeek returns ``prompt_tokens`` / ``completion_tokens`` and provides
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
        validation_alias=AliasChoices("cache_creation_input_tokens", "prompt_cache_miss_tokens"),
    )
    cache_read_input_tokens: int = Field(
        default=0,
        validation_alias=AliasChoices("cache_read_input_tokens", "prompt_cache_hit_tokens"),
    )
    reasoning_tokens: int = 0
    # Provider wire formats disagree about ``input_tokens``: OpenAI/DeepSeek
    # include cached tokens, while Anthropic excludes cache reads/writes. Keep
    # that fact beside the parsed value instead of guessing from magnitudes.
    # Keep it in serialised usage records: without the marker an inclusive
    # OpenAI/DeepSeek count is re-read as Anthropic-exclusive and doubled.
    input_tokens_include_cache: bool | None = Field(
        default=None,
        repr=False,
    )

    @property
    def total_input_tokens(self) -> int:
        """Full prompt size, normalised across provider conventions."""
        cached = self.cache_read_input_tokens + self.cache_creation_input_tokens
        if self.input_tokens_include_cache is True:
            return self.input_tokens
        if self.input_tokens_include_cache is False:
            return self.input_tokens + cached
        # Backward-compatible fallback for Usage objects restored from older
        # data that predates the explicit convention marker.
        return (
            self.input_tokens
            if self.input_tokens >= cached
            else self.input_tokens + cached
        )

    @model_validator(mode="before")
    @classmethod
    def _normalise_provider_fields(cls, data: Any) -> Any:
        """Record token semantics and extract nested OpenAI-style counters."""
        if not isinstance(data, dict):
            return data
        data = dict(data)

        if "input_tokens_include_cache" not in data:
            if "prompt_tokens" in data:
                data["input_tokens_include_cache"] = True
            elif "input_tokens" in data and (
                "cache_read_input_tokens" in data or "cache_creation_input_tokens" in data
            ):
                data["input_tokens_include_cache"] = False

        details = data.get("completion_tokens_details")
        if not data.get("reasoning_tokens") and isinstance(details, dict):
            nested = details.get("reasoning_tokens")
            if isinstance(nested, int):
                data["reasoning_tokens"] = nested

        # OpenAI reports cached input under prompt_tokens_details while its
        # prompt_tokens remains inclusive. Treat the uncached remainder as a
        # cache miss so hit ratios and tiered cost estimates have a denominator.
        prompt_details = data.get("prompt_tokens_details")
        prompt_tokens = data.get("prompt_tokens")
        if isinstance(prompt_details, dict) and isinstance(prompt_tokens, int):
            cached = prompt_details.get("cached_tokens")
            if isinstance(cached, int) and cached >= 0:
                if not any(
                    key in data for key in ("cache_read_input_tokens", "prompt_cache_hit_tokens")
                ):
                    data["cache_read_input_tokens"] = cached
                if not any(
                    key in data
                    for key in (
                        "cache_creation_input_tokens",
                        "prompt_cache_miss_tokens",
                    )
                ):
                    data["cache_creation_input_tokens"] = max(0, prompt_tokens - cached)
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
    # The provider stopped because the output cap was reached
    # (``finish_reason: "length"``), so this sample is a fragment. Without
    # the flag a truncated answer is indistinguishable from a finished one.
    truncated: bool = False


StreamEvent = Annotated[
    StreamTextDelta
    | StreamThinkingDelta
    | StreamToolCallDelta
    | StreamToolCallComplete
    | StreamError
    | StreamDone,
    Field(discriminator="type"),
]
