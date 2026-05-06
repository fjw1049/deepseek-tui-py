from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SendMessageOp:
    content: str
    model: str | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class CancelRequestOp:
    reason: str = "user_cancelled"


EngineOp = SendMessageOp | CancelRequestOp
