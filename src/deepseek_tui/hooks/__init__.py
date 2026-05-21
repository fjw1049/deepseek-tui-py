"""Hooks system for event emission and lifecycle tracking."""

from deepseek_tui.hooks.build import build_hook_dispatcher, build_lifecycle_hook_executor
from deepseek_tui.hooks.dispatcher import HookDispatcher
from deepseek_tui.hooks.executor import HookExecutor
from deepseek_tui.hooks.events import (
    ApprovalLifecycleEvent,
    GenericEventFrameEvent,
    HookEvent,
    JobLifecycleEvent,
    ResponseDeltaEvent,
    ResponseEndEvent,
    ResponseStartEvent,
    SessionLifecycleEvent,
    ToolLifecycleEvent,
)
from deepseek_tui.hooks.sinks import (
    HookSink,
    JsonlHookSink,
    ShellHookSink,
    StdoutHookSink,
    WebhookHookSink,
)

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
    "SessionLifecycleEvent",
    "ShellHookSink",
    "StdoutHookSink",
    "ToolLifecycleEvent",
    "WebhookHookSink",
    "HookExecutor",
    "build_hook_dispatcher",
    "build_lifecycle_hook_executor",
]
