"""Construct a :class:`HookDispatcher` from application config."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.config.models import Config
from deepseek_tui.hooks.dispatcher import HookDispatcher
from deepseek_tui.hooks.executor import HookExecutor
from deepseek_tui.hooks.sinks import JsonlHookSink, ShellHookSink, StdoutHookSink, WebhookHookSink


def build_hook_dispatcher(config: Config) -> HookDispatcher:
    """Wire stdout / JSONL / webhook / shell sinks from ``config.hooks``."""
    dispatcher = HookDispatcher()
    hooks_cfg = config.hooks
    if hooks_cfg.stdout:
        dispatcher.add_sink(StdoutHookSink())
    if hooks_cfg.jsonl_path is not None:
        dispatcher.add_sink(JsonlHookSink(hooks_cfg.jsonl_path.expanduser()))
    for url in hooks_cfg.webhook_urls:
        if url.strip():
            dispatcher.add_sink(WebhookHookSink(url))
    for sh in hooks_cfg.shell_hooks:
        dispatcher.add_sink(
            ShellHookSink(
                event_filter=sh.event,
                command=sh.command,
                timeout=sh.timeout_secs,
            )
        )
    return dispatcher


def build_lifecycle_hook_executor(config: Config, workspace: Path | None = None) -> HookExecutor:
    """Construct a lifecycle :class:`HookExecutor` from ``config.hooks``."""
    ws = (workspace or Path.cwd()).resolve()
    return HookExecutor.from_config(config.hooks, ws)
