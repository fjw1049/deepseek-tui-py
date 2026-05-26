"""/v1/threads CRUD + summary + fork + resume."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import body, manager
from deepseek_tui.app_server.runtime_threads import (
    CreateThreadRequest,
    UpdateThreadRequest,
)

router = APIRouter(prefix="/v1")


@router.get("/threads")
async def list_threads(request: Request) -> list[dict[str, Any]]:
    mgr = manager(request)
    include_archived = request.query_params.get("include_archived", "false") == "true"
    limit_str = request.query_params.get("limit")
    limit = int(limit_str) if limit_str else None
    threads = await mgr.list_threads(include_archived=include_archived, limit=limit)
    return [t.model_dump(mode="json") for t in threads]


@router.post("/threads", status_code=201)
async def create_thread(request: Request) -> JSONResponse:
    mgr = manager(request)
    payload = await body(request)
    req = CreateThreadRequest.model_validate(payload)
    thread = await mgr.create_thread(req)
    return JSONResponse(status_code=201, content=thread.model_dump(mode="json"))


@router.get("/threads/summary")
async def threads_summary(request: Request) -> dict[str, Any]:
    mgr = manager(request)
    return await mgr.threads_summary()


@router.get("/threads/{thread_id}")
async def get_thread_detail(request: Request, thread_id: str) -> dict[str, Any]:
    mgr = manager(request)
    try:
        detail = await mgr.get_thread_detail(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    return detail.model_dump(mode="json")


@router.patch("/threads/{thread_id}")
async def update_thread(request: Request, thread_id: str) -> dict[str, Any]:
    mgr = manager(request)
    payload = await body(request)
    req = UpdateThreadRequest.model_validate(payload)
    try:
        thread = await mgr.update_thread(thread_id, req)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    except ValueError as exc:
        raise api_error(400, str(exc), error="invalid_request") from exc
    return thread.model_dump(mode="json")


@router.post("/threads/{thread_id}/fork", status_code=201)
async def fork_thread(request: Request, thread_id: str) -> JSONResponse:
    mgr = manager(request)
    try:
        forked = await mgr.fork_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    return JSONResponse(status_code=201, content=forked.model_dump(mode="json"))


@router.post("/threads/{thread_id}/resume")
async def resume_thread(request: Request, thread_id: str) -> dict[str, Any]:
    mgr = manager(request)
    try:
        detail = await mgr.resume_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    return detail.model_dump(mode="json")
