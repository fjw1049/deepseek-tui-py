"""App server for HTTP REST and stdio JSON-RPC interfaces."""

from __future__ import annotations

from deepseek_tui.app_server.broadcast import AsyncBroadcast
from deepseek_tui.app_server.routes import build_router
from deepseek_tui.app_server.runtime import AppRuntime, ThreadRecord, ThreadStore
from deepseek_tui.app_server.runtime_threads import (
    RuntimeThreadManagerConfig,
    RuntimeThreadStore,
)
from deepseek_tui.app_server.server import (
    AppServerOptions,
    build_fastapi_app,
    run_http,
    run_stdio,
)
from deepseek_tui.app_server.sse import SseStream
from deepseek_tui.app_server.thread_manager import RuntimeThreadManager

__all__ = [
    "AppRuntime",
    "AppServerOptions",
    "AsyncBroadcast",
    "RuntimeThreadManager",
    "RuntimeThreadManagerConfig",
    "RuntimeThreadStore",
    "SseStream",
    "ThreadRecord",
    "ThreadStore",
    "build_fastapi_app",
    "build_router",
    "run_http",
    "run_stdio",
]
