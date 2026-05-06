"""Prompt-level RPC pair.

Mirrors Rust ``PromptRequest`` (protocol/src/lib.rs:207-214) and
``PromptResponse`` (lib.rs:216-222).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .events import EventFrame

__all__ = ["PromptRequest", "PromptResponse"]


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
