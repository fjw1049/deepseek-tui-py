"""GET /v1/jobs — shell + durable task snapshot for Workbench."""

from __future__ import annotations

from fastapi import APIRouter, Request

from deepseek_tui.app_server.runtime_api.routes._deps import manager

router = APIRouter(prefix="/v1")


@router.get("/jobs")
async def list_jobs(request: Request) -> dict[str, object]:
    thread_id = request.query_params.get("thread_id")
    mgr = manager(request)
    return await mgr.jobs_snapshot(thread_id=thread_id or None)
