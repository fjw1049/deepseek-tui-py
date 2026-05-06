"""HTTP server routes for app server."""

from __future__ import annotations

from typing import Any


async def healthz() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "protocol": "v2",
        "service": "deepseek-app-server",
    }


async def thread_handler(request: dict[str, Any]) -> dict[str, Any]:
    """Handle thread requests."""
    return {
        "thread_id": "stub",
        "status": "not_implemented",
        "thread": None,
        "threads": [],
        "model": None,
        "model_provider": None,
        "cwd": None,
        "approval_policy": None,
        "sandbox": None,
        "events": [],
    }


async def app_handler(request: dict[str, Any]) -> dict[str, Any]:
    """Handle app requests."""
    return {"status": "not_implemented"}


async def prompt_handler(request: dict[str, Any]) -> dict[str, Any]:
    """Handle prompt requests."""
    return {"status": "not_implemented"}


async def tool_handler(request: dict[str, Any]) -> dict[str, Any]:
    """Handle tool execution requests."""
    return {"status": "not_implemented"}


async def jobs_handler() -> dict[str, Any]:
    """Handle jobs list requests."""
    return {"jobs": []}


async def mcp_startup_handler(request: dict[str, Any]) -> dict[str, Any]:
    """Handle MCP startup requests."""
    return {"status": "not_implemented"}
