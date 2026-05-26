"""Helpers to delegate runtime_api routes to :class:`AppRuntime`."""

from __future__ import annotations

from typing import Any

from deepseek_tui.app_server.runtime import AppRuntime
from deepseek_tui.app_server.runtime_api.errors import api_error


def unwrap_runtime_result(result: dict[str, Any]) -> Any:
    """Convert legacy ``{"ok": true, ...}`` envelopes to bare parity JSON."""
    if result.get("ok") is False:
        message = str(result.get("error") or "runtime request failed")
        raise api_error(503, message, error="runtime_error")
    payload = {key: value for key, value in result.items() if key != "ok"}
    return payload


def runtime_from_request(request: Any) -> AppRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise api_error(503, "runtime not configured")
    return runtime
