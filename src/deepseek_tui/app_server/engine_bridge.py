"""Bridge engine events into SSE envelopes.

Mirrors the Rust event-frame path used by ``app-server``: turn_loop
emits EngineEvent dataclasses, and the bridge serializes each one into
``{"event": "<snake_case>", ...}`` dicts that :func:`iter_sse` can frame.

Stage 4.1.next.next wires :class:`AppRuntime.stream_prompt` through this
bridge so the /prompt/stream endpoint streams real assistant deltas and
tool results instead of the 3-frame placeholder.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ElevationRequiredEvent,
    EngineEvent,
    ErrorEvent,
    SandboxDeniedEvent,
    StatusEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)


def engine_event_to_sse(event: EngineEvent) -> dict[str, Any]:
    """Serialize an EngineEvent into the SSE envelope shape.

    The returned dict always carries ``event`` (snake_case tag) plus
    whatever fields the source dataclass exposes. Non-trivial payloads
    (tool calls, approvals) are rendered via ``asdict`` with best-effort
    flattening so the SSE consumer can parse in place.
    """
    if isinstance(event, TurnStartedEvent):
        return {"event": "turn_started", "user_text": event.user_text}
    if isinstance(event, TextDeltaEvent):
        return {"event": "text_delta", "text": event.text}
    if isinstance(event, ThinkingDeltaEvent):
        return {"event": "thinking_delta", "thinking": event.thinking}
    if isinstance(event, ToolCallEvent):
        return {
            "event": "tool_call",
            "tool_call": {
                "id": event.tool_call.id,
                "name": event.tool_call.name,
                "arguments": event.tool_call.arguments,
            },
        }
    if isinstance(event, ToolResultEvent):
        return {
            "event": "tool_result",
            "tool_call_id": event.tool_call_id,
            "tool_name": event.tool_name,
            "content": event.content,
            "success": event.success,
        }
    if isinstance(event, ApprovalRequiredEvent):
        return {
            "event": "approval_required",
            "tool_call_id": event.tool_call_id,
            "request": _render_approval_request(event.request),
        }
    if isinstance(event, ApprovalResolvedEvent):
        return {
            "event": "approval_resolved",
            "tool_call_id": event.tool_call_id,
            "approved": event.approved,
            "reason": event.reason,
        }
    if isinstance(event, SandboxDeniedEvent):
        return {
            "event": "sandbox_denied",
            "tool_call_id": event.tool_call_id,
            "tool_name": event.tool_name,
            "reason": event.reason,
        }
    if isinstance(event, ElevationRequiredEvent):
        return {
            "event": "elevation_required",
            "tool_call_id": event.tool_call_id,
            "tool_name": event.tool_name,
            "reason": event.reason,
            "elevation_kind": event.elevation_kind,
            "command_preview": event.command_preview,
        }
    if isinstance(event, ErrorEvent):
        return {
            "event": "error",
            "message": event.message,
            "retryable": event.retryable,
        }
    if isinstance(event, TurnCancelledEvent):
        return {"event": "turn_cancelled", "reason": event.reason}
    if isinstance(event, TurnCompleteEvent):
        return {
            "event": "turn_complete",
            "assistant_text": _render_assistant_text(event.assistant_message),
            "usage": _render_usage(event.usage),
        }
    if isinstance(event, StatusEvent):
        return {"event": "status", "message": event.message}
    # EngineEvent is a closed Union; this is only reached if a new variant
    # lands without a branch above. Raise instead of silent pass-through.
    raise TypeError(f"Unhandled EngineEvent variant: {type(event).__name__}")


def _render_approval_request(request: Any) -> dict[str, Any]:
    try:
        return asdict(request)
    except TypeError:
        return {"repr": repr(request)}


def _render_assistant_text(message: Any) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                continue
            text_attr = getattr(block, "text", None)
            if isinstance(text_attr, str):
                parts.append(text_attr)
        return "\n".join(parts)
    return str(content or "")


def _render_usage(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    try:
        return asdict(usage)
    except TypeError:
        pass
    if hasattr(usage, "model_dump"):
        dumped = usage.model_dump()
        if isinstance(dumped, dict):
            return dumped
    return None
