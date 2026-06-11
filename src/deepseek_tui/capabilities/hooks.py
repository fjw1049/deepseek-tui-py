"""Hook capability adapter for Engine assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from deepseek_tui.config.models import Config
from deepseek_tui.hooks.build import build_hook_dispatcher, build_lifecycle_hook_executor
from deepseek_tui.hooks.executor import HookExecutor
from deepseek_tui.host.services import ServiceRegistry, ServiceScope


class HookHandle(Protocol):
    hooks: object | None

    def attach_hooks(self, hooks: object) -> None: ...


@dataclass(slots=True)
class HookRuntime:
    executor: HookExecutor


def create_hook_runtime(
    config: Config,
    *,
    workspace: Path,
    handle: HookHandle,
) -> HookRuntime:
    if handle.hooks is None:
        handle.attach_hooks(build_hook_dispatcher(config))
    return HookRuntime(
        executor=build_lifecycle_hook_executor(config, workspace),
    )


def normalize_hook_executor(raw: object | None) -> HookExecutor:
    if isinstance(raw, HookExecutor):
        return raw
    return HookExecutor.disabled()


def attach_engine_hooks(engine: object) -> None:
    """Register hook executor on ToolContext.services for an Engine shell."""
    hook_executor = getattr(engine, "hook_executor", None)
    tool_context = getattr(engine, "tool_context", None)
    if hook_executor is None or tool_context is None:
        return
    attach_hook_bindings(hook_executor, tool_context.services)


def attach_hook_bindings(
    runtime: HookRuntime | HookExecutor,
    services: ServiceRegistry | None = None,
) -> None:
    executor = runtime.executor if isinstance(runtime, HookRuntime) else runtime
    if services is None:
        return
    if services.optional(HookExecutor) is None:
        services.add(
            HookExecutor,
            executor,
            owner="hooks",
            scope=ServiceScope.ENGINE,
        )
    if services.optional_named("hook_executor") is None:
        services.add_named(
            "hook_executor",
            executor,
            owner="hooks",
            scope=ServiceScope.ENGINE,
        )
