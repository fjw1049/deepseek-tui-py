from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from deepseek_tui.protocol.messages import Message


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
