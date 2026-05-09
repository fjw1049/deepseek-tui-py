from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.execpolicy.models import ApprovalRequest
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall, Usage


@dataclass(frozen=True, slots=True)
class StatusEvent:
    message: str


@dataclass(frozen=True, slots=True)
class TurnStartedEvent:
    user_text: str


@dataclass(frozen=True, slots=True)
class TextDeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class ThinkingDeltaEvent:
    thinking: str


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    tool_call: ToolCall


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    tool_call_id: str
    tool_name: str
    content: str
    success: bool


@dataclass(frozen=True, slots=True)
class ApprovalRequiredEvent:
    tool_call_id: str
    request: ApprovalRequest


@dataclass(frozen=True, slots=True)
class ApprovalResolvedEvent:
    tool_call_id: str
    approved: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SandboxDeniedEvent:
    tool_call_id: str
    tool_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class TurnCancelledEvent:
    reason: str


@dataclass(frozen=True, slots=True)
class TurnCompleteEvent:
    assistant_message: Message | None
    usage: Usage | None = None


@dataclass(frozen=True, slots=True)
class UserInputRequiredEvent:
    tool_call_id: str
    questions: list[dict[str, object]]


EngineEvent = (
    StatusEvent
    | TurnStartedEvent
    | TextDeltaEvent
    | ThinkingDeltaEvent
    | ToolCallEvent
    | ToolResultEvent
    | ApprovalRequiredEvent
    | ApprovalResolvedEvent
    | SandboxDeniedEvent
    | ErrorEvent
    | TurnCancelledEvent
    | TurnCompleteEvent
    | UserInputRequiredEvent
)
