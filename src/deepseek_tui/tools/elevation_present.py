"""SSE payload for sandbox elevation (L3) — Workbench parity."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.engine.events import ElevationRequiredEvent


def elevation_request_to_sse_payload(
    elevation_id: str,
    event: ElevationRequiredEvent,
) -> dict[str, object]:
    return {
        "elevation_id": elevation_id,
        "tool_call_id": elevation_id,
        "tool_name": event.tool_name,
        "title": "Sandbox blocked this command",
        "description": event.reason,
        "reason": event.reason,
        "elevation_kind": event.elevation_kind,
        "primary_preview": event.command_preview or None,
        "risk": "destructive",
        "risk_level": "high",
    }
