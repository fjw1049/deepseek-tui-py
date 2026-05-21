"""Hook event definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResponseStartEvent:
    """Response stream started."""

    response_id: str


@dataclass
class ResponseDeltaEvent:
    """Response delta received."""

    response_id: str
    delta: str


@dataclass
class ResponseEndEvent:
    """Response stream ended."""

    response_id: str


@dataclass
class ToolLifecycleEvent:
    """Tool execution lifecycle event."""

    response_id: str
    tool_name: str
    phase: str
    payload: dict[str, Any]


@dataclass
class JobLifecycleEvent:
    """Job lifecycle event."""

    job_id: str
    phase: str
    progress: int | None = None
    detail: str | None = None


@dataclass
class ApprovalLifecycleEvent:
    """Approval lifecycle event."""

    approval_id: str
    phase: str
    reason: str | None = None


@dataclass
class GenericEventFrameEvent:
    """Generic event frame wrapper."""

    frame: dict[str, Any]  # Generic event payload


@dataclass
class SessionLifecycleEvent:
    """Session lifecycle event."""

    session_id: str
    phase: str  # "start" | "end"
    turns: int | None = None


HookEvent = (
    ResponseStartEvent
    | ResponseDeltaEvent
    | ResponseEndEvent
    | ToolLifecycleEvent
    | JobLifecycleEvent
    | ApprovalLifecycleEvent
    | GenericEventFrameEvent
    | SessionLifecycleEvent
)


def event_to_dict(event: HookEvent) -> dict[str, Any]:
    """Convert hook event to JSON-serializable dict."""
    if isinstance(event, ResponseStartEvent):
        return {"type": "response_start", "response_id": event.response_id}
    elif isinstance(event, ResponseDeltaEvent):
        return {
            "type": "response_delta",
            "response_id": event.response_id,
            "delta": event.delta,
        }
    elif isinstance(event, ResponseEndEvent):
        return {"type": "response_end", "response_id": event.response_id}
    elif isinstance(event, ToolLifecycleEvent):
        return {
            "type": "tool_lifecycle",
            "response_id": event.response_id,
            "tool_name": event.tool_name,
            "phase": event.phase,
            "payload": event.payload,
        }
    elif isinstance(event, JobLifecycleEvent):
        return {
            "type": "job_lifecycle",
            "job_id": event.job_id,
            "phase": event.phase,
            "progress": event.progress,
            "detail": event.detail,
        }
    elif isinstance(event, ApprovalLifecycleEvent):
        return {
            "type": "approval_lifecycle",
            "approval_id": event.approval_id,
            "phase": event.phase,
            "reason": event.reason,
        }
    elif isinstance(event, GenericEventFrameEvent):
        return {"type": "generic_event_frame", "frame": event.frame}
    elif isinstance(event, SessionLifecycleEvent):
        d: dict[str, Any] = {
            "type": "session_lifecycle",
            "session_id": event.session_id,
            "phase": event.phase,
        }
        if event.turns is not None:
            d["turns"] = event.turns
        return d
    # Unreachable due to exhaustive union check
    return {"type": "serialization_error"}  # type: ignore[unreachable]
