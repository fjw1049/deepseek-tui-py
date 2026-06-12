"""IPC event frames + MCP lifecycle types.

Consolidates the former events.py and mcp_lifecycle.py.
"""

from __future__ import annotations



from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_serializer, model_validator

from .approval import ExecApprovalRequestEvent

__all__ = [
    "EventFrame",
    # MCP lifecycle
    "McpStartupCompleteEvent",
    "McpStartupFailure",
    "McpStartupStatus",
    "McpStartupUpdateEvent",
    # Event frame variants
    "ApplyPatchApprovalRequestEvent",
    "ElicitationRequestEvent",
    "ErrorEventFrame",
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
]


# ============================================================================
# MCP startup lifecycle (formerly mcp_lifecycle.py)
# ============================================================================


class _StatusStarting(BaseModel):
    type: Literal["starting"] = "starting"


class _StatusReady(BaseModel):
    type: Literal["ready"] = "ready"


class _StatusCancelled(BaseModel):
    type: Literal["cancelled"] = "cancelled"


class _StatusFailed(BaseModel):
    type: Literal["failed"] = "failed"
    error: str


_StatusVariants = (
    Annotated[
        _StatusStarting | _StatusReady | _StatusCancelled | _StatusFailed,
        Field(discriminator="type"),
    ]
)


class McpStartupStatus(RootModel[_StatusVariants]):
    @classmethod
    def starting(cls) -> McpStartupStatus:
        return cls(_StatusStarting())

    @classmethod
    def ready(cls) -> McpStartupStatus:
        return cls(_StatusReady())

    @classmethod
    def cancelled(cls) -> McpStartupStatus:
        return cls(_StatusCancelled())

    @classmethod
    def failed(cls, error: str) -> McpStartupStatus:
        return cls(_StatusFailed(error=error))

    @model_serializer(mode="plain")
    def _serialise(self) -> Any:
        inner = self.root
        if isinstance(inner, _StatusFailed):
            return {"failed": {"error": inner.error}}
        return inner.type

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"type": data}
        if isinstance(data, dict) and "failed" in data and "type" not in data:
            payload = data["failed"]
            if isinstance(payload, dict):
                return {"type": "failed", **payload}
        return data


class McpStartupUpdateEvent(BaseModel):
    server_name: str
    status: McpStartupStatus


class McpStartupFailure(BaseModel):
    server_name: str
    error: str


class McpStartupCompleteEvent(BaseModel):
    ready: list[str] = Field(default_factory=list)
    failed: list[McpStartupFailure] = Field(default_factory=list)
    cancelled: list[str] = Field(default_factory=list)


# ============================================================================
# Event frame variants
# ============================================================================

_BASE = ConfigDict(extra="forbid")


# ---- Response lifecycle ----

class ResponseStartEvent(BaseModel):
    model_config = _BASE
    event: Literal["response_start"] = "response_start"
    response_id: str


class ResponseDeltaEvent(BaseModel):
    model_config = _BASE
    event: Literal["response_delta"] = "response_delta"
    response_id: str
    delta: str


class ResponseEndEvent(BaseModel):
    model_config = _BASE
    event: Literal["response_end"] = "response_end"
    response_id: str


# ---- Tool calls ----

class ToolCallStartEvent(BaseModel):
    model_config = _BASE
    event: Literal["tool_call_start"] = "tool_call_start"
    response_id: str
    tool_name: str
    arguments: Any


class ToolCallResultEvent(BaseModel):
    model_config = _BASE
    event: Literal["tool_call_result"] = "tool_call_result"
    response_id: str
    tool_name: str
    output: Any


# ---- MCP startup + tool ----

class McpStartupUpdateEventFrame(BaseModel):
    model_config = _BASE
    event: Literal["mcp_startup_update"] = "mcp_startup_update"
    update: McpStartupUpdateEvent


class McpStartupCompleteEventFrame(BaseModel):
    model_config = _BASE
    event: Literal["mcp_startup_complete"] = "mcp_startup_complete"
    summary: McpStartupCompleteEvent


class McpToolCallBeginEvent(BaseModel):
    model_config = _BASE
    event: Literal["mcp_tool_call_begin"] = "mcp_tool_call_begin"
    server_name: str
    tool_name: str


class McpToolCallEndEvent(BaseModel):
    model_config = _BASE
    event: Literal["mcp_tool_call_end"] = "mcp_tool_call_end"
    server_name: str
    tool_name: str
    ok: bool


# ---- Approval / elicitation ----

class ExecApprovalRequestEventFrame(BaseModel):
    model_config = _BASE
    event: Literal["exec_approval_request"] = "exec_approval_request"
    request: ExecApprovalRequestEvent


class ApplyPatchApprovalRequestEvent(BaseModel):
    model_config = _BASE
    event: Literal["apply_patch_approval_request"] = "apply_patch_approval_request"
    request: ExecApprovalRequestEvent


class ElicitationRequestEvent(BaseModel):
    model_config = _BASE
    event: Literal["elicitation_request"] = "elicitation_request"
    server_name: str
    request_id: str
    prompt: str


# ---- Exec / patch ----

class ExecCommandBeginEvent(BaseModel):
    model_config = _BASE
    event: Literal["exec_command_begin"] = "exec_command_begin"
    command: str
    cwd: str


class ExecCommandOutputDeltaEvent(BaseModel):
    model_config = _BASE
    event: Literal["exec_command_output_delta"] = "exec_command_output_delta"
    command: str
    delta: str


class ExecCommandEndEvent(BaseModel):
    model_config = _BASE
    event: Literal["exec_command_end"] = "exec_command_end"
    command: str
    exit_code: int


class PatchApplyBeginEvent(BaseModel):
    model_config = _BASE
    event: Literal["patch_apply_begin"] = "patch_apply_begin"
    path: str


class PatchApplyEndEvent(BaseModel):
    model_config = _BASE
    event: Literal["patch_apply_end"] = "patch_apply_end"
    path: str
    ok: bool


# ---- Turn lifecycle + error ----

class TurnStartedEvent(BaseModel):
    model_config = _BASE
    event: Literal["turn_started"] = "turn_started"
    turn_id: str


class TurnCompleteEvent(BaseModel):
    model_config = _BASE
    event: Literal["turn_complete"] = "turn_complete"
    turn_id: str


class TurnAbortedEvent(BaseModel):
    model_config = _BASE
    event: Literal["turn_aborted"] = "turn_aborted"
    turn_id: str
    reason: str


class ErrorEventFrame(BaseModel):
    model_config = _BASE
    event: Literal["error"] = "error"
    response_id: str
    message: str


# ---- Discriminated union ----

EventFrame = Annotated[
    ResponseStartEvent
    | ResponseDeltaEvent
    | ResponseEndEvent
    | ToolCallStartEvent
    | ToolCallResultEvent
    | McpStartupUpdateEventFrame
    | McpStartupCompleteEventFrame
    | McpToolCallBeginEvent
    | McpToolCallEndEvent
    | ExecApprovalRequestEventFrame
    | ApplyPatchApprovalRequestEvent
    | ElicitationRequestEvent
    | ExecCommandBeginEvent
    | ExecCommandOutputDeltaEvent
    | ExecCommandEndEvent
    | PatchApplyBeginEvent
    | PatchApplyEndEvent
    | TurnStartedEvent
    | TurnCompleteEvent
    | TurnAbortedEvent
    | ErrorEventFrame,
    Field(discriminator="event"),
]
