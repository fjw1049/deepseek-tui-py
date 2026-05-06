"""Hooks system for event emission and lifecycle tracking."""

from deepseek_tui.hooks.dispatcher import HookDispatcher
from deepseek_tui.hooks.events import (
    ApprovalLifecycleEvent,
    GenericEventFrameEvent,
    HookEvent,
    JobLifecycleEvent,
    ResponseDeltaEvent,
    ResponseEndEvent,
    ResponseStartEvent,
    ToolLifecycleEvent,
)
from deepseek_tui.hooks.sinks import HookSink, JsonlHookSink, StdoutHookSink, WebhookHookSink

__all__ = [
    "ApprovalLifecycleEvent",
    "GenericEventFrameEvent",
    "HookDispatcher",
    "HookEvent",
    "HookSink",
    "JobLifecycleEvent",
    "JsonlHookSink",
    "ResponseDeltaEvent",
    "ResponseEndEvent",
    "ResponseStartEvent",
    "StdoutHookSink",
    "ToolLifecycleEvent",
    "WebhookHookSink",
]
