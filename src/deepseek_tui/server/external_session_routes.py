"""Local, per-session imports; the UI batches requests with stop/retry support."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from deepseek_tui.server.external_sessions import History, Source, import_session, scan_sessions

router = APIRouter(prefix="/v1/external-sessions", tags=["data"])


class ScanRequest(BaseModel):
    source: Source
    root: str | None = None


class ImportRequest(ScanRequest):
    path: str
    session_id: str
    workspace: str | None = None


@router.post("/scan")
async def scan(request: Request, payload: ScanRequest) -> dict:
    from deepseek_tui.server.routes import manager

    mgr = manager(request)
    try:
        return await asyncio.to_thread(scan_sessions, mgr.store, payload.source, payload.root)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/import")
async def import_one(request: Request, payload: ImportRequest) -> dict:
    from deepseek_tui.server.routes import manager
    from deepseek_tui.server.threads.errors import TurnConflictError
    from deepseek_tui.tools.runtime import default_runtime_model

    mgr = manager(request)

    async def commit() -> dict:
        identity = History(payload.source, Path(payload.path), session_id=payload.session_id)
        async with mgr._hold_thread_operation(identity.thread_id):
            result = await asyncio.to_thread(
                import_session,
                mgr.store,
                **payload.model_dump(),
                model=default_runtime_model(mgr.config),
                provider=mgr.config.provider,
            )
            if result["status"] == "linked":
                await mgr._evict_active_thread(result["thread_id"])
            return result

    try:
        return await mgr._complete_mutation(commit())
    except TurnConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "The source session is unavailable; scan again") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
