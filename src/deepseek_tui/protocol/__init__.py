"""Protocol types for DeepSeek-TUI.

The package splits into two layers:

* **LLM client layer** — :class:`Message`, :class:`ContentBlock`,
  :class:`MessageRequest`, :class:`StreamEvent`, :class:`Usage`,
  :class:`ToolCall`, :class:`ErrorEnvelope`. These describe the
  conversation history and the streaming events the LLM client emits.
* **IPC layer** — Rust-parity types from
  ``crates/protocol/src/lib.rs`` for stdio JSON-RPC and SSE traffic
  between app-server, TUI, hooks, MCP, etc. Includes
  :class:`Envelope`, :class:`Thread`, :class:`ThreadRequest`,
  :class:`PromptRequest`, :class:`EventFrame` (21
  variants), :class:`ToolPayload`, :class:`ToolOutput`,
  :class:`ReviewDecision`, :class:`AskForApproval`, MCP lifecycle.
"""

from .approval import (
    AskForApproval,
    ExecApprovalRequestEvent,
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
)
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
from .events import (
    ApplyPatchApprovalRequestEvent,
    ElicitationRequestEvent,
    ErrorEventFrame,
    EventFrame,
    ExecApprovalRequestEventFrame,
    ExecCommandBeginEvent,
    ExecCommandEndEvent,
    ExecCommandOutputDeltaEvent,
    McpStartupCompleteEventFrame,
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
from .ipc import Envelope
from .mcp_lifecycle import (
    McpStartupCompleteEvent,
    McpStartupFailure,
    McpStartupStatus,
    McpStartupUpdateEvent,
)
from .messages import (
    Message,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from .prompt import PromptRequest, PromptResponse
from .requests import MessageRequest
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
from .threads import (
    SessionSource,
    Thread,
    ThreadArchiveRequest,
    ThreadCreateRequest,
    ThreadForkParams,
    ThreadForkRequest,
    ThreadListParams,
    ThreadListRequest,
    ThreadMessageRequest,
    ThreadReadParams,
    ThreadReadRequest,
    ThreadRequest,
    ThreadResponse,
    ThreadResumeParams,
    ThreadResumeRequest,
    ThreadSetNameParams,
    ThreadSetNameRequest,
    ThreadStartParams,
    ThreadStartRequest,
    ThreadStatus,
    ThreadUnarchiveRequest,
)
from .tool_payload import (
    LocalShellParams,
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

__all__ = [
    # LLM client layer
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
    # MCP lifecycle
    "McpStartupCompleteEvent",
    "McpStartupFailure",
    "McpStartupStatus",
    "McpStartupUpdateEvent",
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
    # Event frames (21 variants)
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
    # Threads
    "SessionSource",
    "Thread",
    "ThreadArchiveRequest",
    "ThreadCreateRequest",
    "ThreadForkParams",
    "ThreadForkRequest",
    "ThreadListParams",
    "ThreadListRequest",
    "ThreadMessageRequest",
    "ThreadReadParams",
    "ThreadReadRequest",
    "ThreadRequest",
    "ThreadResponse",
    "ThreadResumeParams",
    "ThreadResumeRequest",
    "ThreadSetNameParams",
    "ThreadSetNameRequest",
    "ThreadStartParams",
    "ThreadStartRequest",
    "ThreadStatus",
    "ThreadUnarchiveRequest",
    # Prompt
    "PromptRequest",
    "PromptResponse",
]
