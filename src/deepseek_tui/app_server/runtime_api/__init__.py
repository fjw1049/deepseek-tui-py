"""Rust-parity HTTP/SSE runtime API for DeepSeek Workbench."""

from deepseek_tui.app_server.runtime_api.app import attach_runtime_api, build_runtime_api_app
from deepseek_tui.app_server.runtime_api.auth import ResolvedRuntimeAuth, resolve_runtime_auth

__all__ = [
    "ResolvedRuntimeAuth",
    "attach_runtime_api",
    "build_runtime_api_app",
    "resolve_runtime_auth",
]
