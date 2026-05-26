"""GET /v1/sessions + export Workbench threads back to TUI session files."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import manager
from deepseek_tui.app_server.session_catalog import (
    export_thread_to_tui_session,
    list_unified_sessions,
)
from deepseek_tui.config.paths import user_sessions_dir

router = APIRouter(prefix="/v1")


@router.get("/sessions")
async def list_sessions(request: Request) -> dict[str, Any]:
    mgr = manager(request)
    limit_str = request.query_params.get("limit")
    limit = int(limit_str) if limit_str else 50
    threads = await mgr.list_threads(include_archived=False)
    sessions = list_unified_sessions(mgr.store, threads, limit=limit)
    return {
        "dir": str(user_sessions_dir()),
        "sessions": sessions,
    }


@router.post("/threads/{thread_id}/export-session")
async def export_session(request: Request, thread_id: str) -> dict[str, Any]:
    mgr = manager(request)
    try:
        thread = mgr.store.load_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    session_id = request.query_params.get("session_id")
    try:
        path, sid = export_thread_to_tui_session(
            mgr.store,
            thread,
            session_id=session_id,
        )
    except ValueError as exc:
        raise api_error(400, str(exc), error="invalid_export") from exc

    thread.source_session_id = sid
    thread.source_session_path = str(path)
    thread.updated_at = datetime.now(timezone.utc)
    mgr.store.save_thread(thread)

    return {
        "session_id": sid,
        "path": str(path),
        "thread_id": thread.id,
    }
