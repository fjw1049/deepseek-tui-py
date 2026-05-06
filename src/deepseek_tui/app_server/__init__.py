"""App server for HTTP REST and stdio JSON-RPC interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from deepseek_tui.app_server.routes import (
    app_handler,
    healthz,
    jobs_handler,
    mcp_startup_handler,
    prompt_handler,
    thread_handler,
    tool_handler,
)
from deepseek_tui.app_server.server import run_http, run_stdio
from deepseek_tui.app_server.sse import SseStream


@dataclass(slots=True)
class AppServerOptions:
    """App server configuration."""

    listen: str = "127.0.0.1:8080"
    config_path: Path | None = None


__all__ = [
    "AppServerOptions",
    "SseStream",
    "app_handler",
    "healthz",
    "jobs_handler",
    "mcp_startup_handler",
    "prompt_handler",
    "run_http",
    "run_stdio",
    "thread_handler",
    "tool_handler",
]
