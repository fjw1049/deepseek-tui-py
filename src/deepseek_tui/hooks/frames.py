"""Bridge protocol EventFrame models into observability hook events."""

from __future__ import annotations

from pydantic import BaseModel

from deepseek_tui.hooks.events import GenericEventFrameEvent


def generic_event_frame(frame: BaseModel) -> GenericEventFrameEvent:
    """Wrap a protocol frame for :class:`HookDispatcher` emission."""
    return GenericEventFrameEvent(frame=frame.model_dump(mode="json"))
