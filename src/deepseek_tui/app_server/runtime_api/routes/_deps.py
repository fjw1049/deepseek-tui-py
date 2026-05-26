"""Shared request helpers + ValueError classifier for runtime_api routes."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.thread_manager import RuntimeThreadManager


def manager(request: Request) -> RuntimeThreadManager:
    mgr = getattr(request.app.state, "thread_manager", None)
    if mgr is None:
        raise api_error(503, "runtime thread manager not configured")
    return mgr


def approval_bridge(request: Request) -> Any:
    bridge = getattr(request.app.state, "approval_bridge", None)
    if bridge is None:
        raise api_error(503, "approval bridge not configured")
    return bridge


async def body(request: Request) -> dict[str, Any]:
    if request.headers.get("content-length", "0") == "0":
        return {}
    try:
        data = await request.json()
    except ValueError as exc:
        raise api_error(400, "request body must be valid JSON", error="invalid_json") from exc
    if not isinstance(data, dict):
        raise api_error(400, "request body must be a JSON object", error="invalid_json") from None
    return data


def classify_turn_value_error(exc: ValueError) -> Exception:
    """Map RuntimeThreadManager ``ValueError`` to HTTP shape.

    Active-turn collisions are 409 ``turn_conflict`` (mirrors Rust ``ApiError``
    shape). Empty prompt / not-loaded / wrong turn id are caller errors → 400.
    """
    msg = str(exc)
    lowered = msg.lower()
    if "already has an active turn" in lowered:
        return api_error(409, msg, error="turn_conflict")
    if "is not active" in lowered or "is not loaded" in lowered:
        return api_error(409, msg, error="turn_not_active")
    return api_error(400, msg, error="invalid_request")
