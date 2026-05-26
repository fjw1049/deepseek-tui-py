"""GET /v1/threads/{id}/events — long-lived SSE with backlog replay."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import manager
from deepseek_tui.app_server.runtime_api.sse import stream_thread_events

router = APIRouter(prefix="/v1")


@router.get("/threads/{thread_id}/events")
async def stream_events(request: Request, thread_id: str) -> StreamingResponse:
    mgr = manager(request)
    try:
        await mgr.get_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    since_str = request.query_params.get("since_seq")
    since_seq = int(since_str) if since_str else None
    generator = stream_thread_events(
        mgr,
        thread_id,
        since_seq,
        is_disconnected=request.is_disconnected,
    )
    return StreamingResponse(generator, media_type="text/event-stream")
