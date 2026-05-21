"""App server for HTTP REST and stdio JSON-RPC interfaces."""

from __future__ import annotations

from deepseek_tui.app_server.runtime import AppRuntime, ThreadRecord, ThreadStore
from deepseek_tui.app_server.runtime_threads import (
    RuntimeThreadManagerConfig,
    RuntimeThreadStore,
)
from deepseek_tui.app_server.thread_manager import RuntimeThreadManager

__all__ = [
    "AppRuntime",
    "AppServerOptions",
    "RuntimeThreadManager",
    "RuntimeThreadManagerConfig",
    "RuntimeThreadStore",
    "ThreadRecord",
    "ThreadStore",
    "build_fastapi_app",
    "build_router",
    "run_http",
    "run_stdio",
]


def __getattr__(name: str) -> object:
    if name == "build_router":
        from deepseek_tui.app_server.routes import build_router

        return build_router
    if name in {"AppServerOptions", "build_fastapi_app", "run_http", "run_stdio"}:
        from deepseek_tui.app_server import server as server_mod

        return getattr(server_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
