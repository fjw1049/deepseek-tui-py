"""Rust-parity HTTP/SSE runtime API for DeepSeek Workbench."""

from deepseek_tui.app_server.runtime_api.app import attach_runtime_api
from deepseek_tui.app_server.runtime_api.auth import ResolvedRuntimeAuth, resolve_runtime_auth

__all__ = [
    "ResolvedRuntimeAuth",
    "attach_runtime_api",
    "resolve_runtime_auth",
]
