"""LLM message types + request/prompt models.

Consolidates the former messages.py, requests.py, and prompt.py.
"""

from __future__ import annotations



from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .events import EventFrame


# ============================================================================
# Content blocks & Message
# ============================================================================

from enum import Enum


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingBlock(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: str | None = None


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = Annotated[
    TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]


class Message(BaseModel):
    role: Role
    content: list[ContentBlock] = Field(default_factory=list)

    @classmethod
    def system(cls, text: str) -> Message:
        return cls(role=Role.SYSTEM, content=[TextBlock(text=text)])

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role=Role.USER, content=[TextBlock(text=text)])

    @classmethod
    def assistant(cls, text: str) -> Message:
        return cls(role=Role.ASSISTANT, content=[TextBlock(text=text)])

    @classmethod
    def assistant_with_tools(cls, blocks: list[ToolUseBlock]) -> Message:
        from typing import cast
        return cls(role=Role.ASSISTANT, content=cast(list[ContentBlock], blocks))

    @classmethod
    def tool_result(cls, tool_use_id: str, content: str, is_error: bool = False) -> Message:
        return cls(
            role=Role.TOOL,
            content=[ToolResultBlock(tool_use_id=tool_use_id, content=content, is_error=is_error)],
        )


# ============================================================================
# MessageRequest (formerly requests.py)
# ============================================================================


class MessageRequest(BaseModel):
    model: str
    messages: list[Message] = Field(default_factory=list)
    system_prompt: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    stream: bool = True


# ============================================================================
# PromptRequest / PromptResponse (formerly prompt.py)
# ============================================================================


class PromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str | None = None
    prompt: str
    model: str | None = None


class PromptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: str
    model: str
    events: list[EventFrame] = Field(default_factory=list)


# ============================================================================
# IPC Envelope (formerly ipc.py)
# ============================================================================

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """Generic IPC envelope: ``{request_id, thread_id?, body}``."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str
    thread_id: str | None = None
    body: T
