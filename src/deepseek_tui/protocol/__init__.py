"""Protocol types for DeepSeek-TUI.

Two layers:
* LLM client layer — Message, ContentBlock, MessageRequest, StreamEvent, Usage, ToolCall
* IPC layer — Envelope, Thread, EventFrame (21 variants), ToolPayload, ReviewDecision, etc.
"""

from enum import Enum as _Enum
from typing import Any as _Any

from pydantic import BaseModel as _BaseModel
from pydantic import Field as _Field


class ErrorKind(str, _Enum):
    CONFIG = "config"
    AUTH = "auth"
    NETWORK = "network"
    TOOL = "tool"
    RATE_LIMIT = "rate_limit"
    INTERNAL = "internal"


class ErrorEnvelope(_BaseModel):
    kind: ErrorKind
    message: str
    retryable: bool = False
    metadata: dict[str, _Any] = _Field(default_factory=dict)


from .approval import (
    AskForApproval,
    ExecApprovalRequestEvent,
    LocalShellParams,
    NetworkApprovalContext,
    NetworkPolicyAmendment,
    NetworkPolicyRuleAction,
    ReviewDecision,
    ReviewDecisionAbort,
    ReviewDecisionApproved,
    ReviewDecisionApprovedExecpolicyAmendment,
    ReviewDecisionApprovedForSession,
    ReviewDecisionDenied,
    ReviewDecisionNetworkPolicyAmendment,
    ToolKind,
    ToolOutput,
    ToolOutputFunction,
    ToolOutputMcp,
    ToolPayload,
    ToolPayloadCustom,
    ToolPayloadFunction,
    ToolPayloadLocalShell,
    ToolPayloadMcp,
)
from .events import (
    ApplyPatchApprovalRequestEvent,
    ElicitationRequestEvent,
    ErrorEventFrame,
    EventFrame,
    ExecApprovalRequestEventFrame,
    ExecCommandBeginEvent,
    ExecCommandEndEvent,
    ExecCommandOutputDeltaEvent,
    McpStartupCompleteEvent,
    McpStartupCompleteEventFrame,
    McpStartupFailure,
    McpStartupStatus,
    McpStartupUpdateEvent,
    McpStartupUpdateEventFrame,
    McpToolCallBeginEvent,
    McpToolCallEndEvent,
    PatchApplyBeginEvent,
    PatchApplyEndEvent,
    ResponseDeltaEvent,
    ResponseEndEvent,
    ResponseStartEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    TurnAbortedEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)
from .messages import (
    ContentBlock,
    Envelope,
    Message,
    MessageRequest,
    PromptRequest,
    PromptResponse,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from .responses import (
    StreamDone,
    StreamError,
    StreamEvent,
    StreamEventType,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
    StreamToolCallDelta,
    ToolCall,
    Usage,
)
__all__ = [
    # LLM client layer
    "ContentBlock",
    "ErrorEnvelope",
    "ErrorKind",
    "Message",
    "MessageRequest",
    "Role",
    "StreamDone",
    "StreamError",
    "StreamEvent",
    "StreamEventType",
    "StreamTextDelta",
    "StreamThinkingDelta",
    "StreamToolCallComplete",
    "StreamToolCallDelta",
    "TextBlock",
    "ThinkingBlock",
    "ToolCall",
    "ToolResultBlock",
    "ToolUseBlock",
    "Usage",
    # IPC envelope
    "Envelope",
    # Approval
    "AskForApproval",
    "ExecApprovalRequestEvent",
    "NetworkApprovalContext",
    "NetworkPolicyAmendment",
    "NetworkPolicyRuleAction",
    "ReviewDecision",
    "ReviewDecisionAbort",
    "ReviewDecisionApproved",
    "ReviewDecisionApprovedExecpolicyAmendment",
    "ReviewDecisionApprovedForSession",
    "ReviewDecisionDenied",
    "ReviewDecisionNetworkPolicyAmendment",
    # Tool payload + output
    "LocalShellParams",
    "ToolKind",
    "ToolOutput",
    "ToolOutputFunction",
    "ToolOutputMcp",
    "ToolPayload",
    "ToolPayloadCustom",
    "ToolPayloadFunction",
    "ToolPayloadLocalShell",
    "ToolPayloadMcp",
    # MCP lifecycle
    "McpStartupCompleteEvent",
    "McpStartupFailure",
    "McpStartupStatus",
    "McpStartupUpdateEvent",
    # Event frames
    "ApplyPatchApprovalRequestEvent",
    "ElicitationRequestEvent",
    "ErrorEventFrame",
    "EventFrame",
    "ExecApprovalRequestEventFrame",
    "ExecCommandBeginEvent",
    "ExecCommandEndEvent",
    "ExecCommandOutputDeltaEvent",
    "McpStartupCompleteEventFrame",
    "McpStartupUpdateEventFrame",
    "McpToolCallBeginEvent",
    "McpToolCallEndEvent",
    "PatchApplyBeginEvent",
    "PatchApplyEndEvent",
    "ResponseDeltaEvent",
    "ResponseEndEvent",
    "ResponseStartEvent",
    "ToolCallResultEvent",
    "ToolCallStartEvent",
    "TurnAbortedEvent",
    "TurnCompleteEvent",
    "TurnStartedEvent",
    # Prompt
    "PromptRequest",
    "PromptResponse",
]
