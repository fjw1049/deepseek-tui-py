from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, Field


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
        return cls(role=Role.ASSISTANT, content=cast(list[ContentBlock], blocks))

    @classmethod
    def tool_result(cls, tool_use_id: str, content: str, is_error: bool = False) -> Message:
        return cls(
            role=Role.TOOL,
            content=[ToolResultBlock(tool_use_id=tool_use_id, content=content, is_error=is_error)],
        )
