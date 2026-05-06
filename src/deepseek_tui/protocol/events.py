"""IPC event frames.

Mirrors Rust ``EventFrame`` (protocol/src/lib.rs:369-451).

Rust uses ``#[serde(tag = "event", rename_all = "snake_case")]`` so each
variant serialises to a flat object whose ``event`` field doubles as the
discriminator. Example::

    {"event": "turn_complete", "turn_id": "..."}
    {"event": "response_delta", "response_id": "...", "delta": "..."}
    {"event": "exec_approval_request", "request": {...}}

There are 21 variants; the order below mirrors the Rust file.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .approval import ExecApprovalRequestEvent
from .mcp_lifecycle import McpStartupCompleteEvent, McpStartupUpdateEvent

__all__ = [
    "EventFrame",
    # variants — exported for callers that want to construct directly
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


# A common config: every variant forbids extras and keeps field-name
# casing exactly as Rust emits.
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
