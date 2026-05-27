from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from deepseek_tui.execpolicy.models import ApprovalRequest
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall, Usage

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent.mailbox import MailboxMessage


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
    metadata: dict[str, object] | None = None


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
class ElevationRequiredEvent:
    """L3 sandbox: OS policy blocked the shell call; user may elevate once."""

    tool_call_id: str
    tool_name: str
    reason: str
    elevation_kind: str
    command_preview: str = ""


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class TurnCancelledEvent:
    reason: str


@dataclass(frozen=True, slots=True)
class SubAgentMailboxEvent:
    """Structured sub-agent progress (mirrors Rust ``Event::SubAgentMailbox``)."""

    seq: int
    message: MailboxMessage


@dataclass(frozen=True, slots=True)
class RlmProgressEvent:
    """RLM iteration progress while the ``rlm`` tool is executing."""

    iteration: int
    summary: str
    rpc_count: int = 0


@dataclass(frozen=True, slots=True)
class SessionActivityEvent:
    """Background work snapshot (sub-agents + durable tasks)."""

    running_subagents: int
    running_tasks: int
    message: str = ""


@dataclass(frozen=True, slots=True)
class TurnCompleteEvent:
    assistant_message: Message | None
    usage: Usage | None = None
    # Cumulative session cost (USD) — populated when ``Engine`` knows
    # how to price the model. ``None`` when pricing is unknown (off-
    # platform providers, unrecognised model) so the UI can hide rather
    # than show a misleading zero.
    session_cost_usd: float | None = None
    session_cost_cny: float | None = None
    # Convenience snapshot so the UI can render the cache-hit chip
    # without having to keep state of its own. Both default to 0 when
    # the provider didn't return cache details.
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    # Non-blocking background work still running after this turn ends.
    running_subagents: int = 0
    running_tasks: int = 0


@dataclass(frozen=True, slots=True)
class UserInputRequiredEvent:
    tool_call_id: str
    questions: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class SessionStartedEvent:
    session_id: str


@dataclass(frozen=True, slots=True)
class SessionEndedEvent:
    session_id: str
    turns: int


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
    | ElevationRequiredEvent
    | ErrorEvent
    | TurnCancelledEvent
    | TurnCompleteEvent
    | SubAgentMailboxEvent
    | RlmProgressEvent
    | SessionActivityEvent
    | UserInputRequiredEvent
    | SessionStartedEvent
    | SessionEndedEvent
)
