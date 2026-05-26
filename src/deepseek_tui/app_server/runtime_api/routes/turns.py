"""/v1/threads/{id}/turns lifecycle: start / interrupt / steer / compact."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import (
    body,
    classify_turn_value_error,
    manager,
)
from deepseek_tui.app_server.runtime_threads import (
    CompactThreadRequest,
    StartTurnRequest,
    SteerTurnRequest,
)

router = APIRouter(prefix="/v1")


@router.post("/threads/{thread_id}/turns", status_code=201)
async def start_turn(request: Request, thread_id: str) -> JSONResponse:
    mgr = manager(request)
    payload = await body(request)
    req = StartTurnRequest.model_validate(payload)
    try:
        turn = await mgr.start_turn(thread_id, req)
        thread = await mgr.get_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    except ValueError as exc:
        raise classify_turn_value_error(exc) from exc
    return JSONResponse(
        status_code=201,
        content={
            "thread": thread.model_dump(mode="json"),
            "turn": turn.model_dump(mode="json"),
        },
    )


@router.post("/threads/{thread_id}/turns/{turn_id}/interrupt")
async def interrupt_turn(
    request: Request, thread_id: str, turn_id: str
) -> dict[str, Any]:
    mgr = manager(request)
    try:
        turn = await mgr.interrupt_turn(thread_id, turn_id)
    except ValueError as exc:
        raise classify_turn_value_error(exc) from exc
    return turn.model_dump(mode="json")


@router.post("/threads/{thread_id}/turns/{turn_id}/steer")
async def steer_turn(
    request: Request, thread_id: str, turn_id: str
) -> dict[str, Any]:
    mgr = manager(request)
    payload = await body(request)
    req = SteerTurnRequest.model_validate(payload)
    try:
        turn = await mgr.steer_turn(thread_id, turn_id, req)
    except ValueError as exc:
        raise classify_turn_value_error(exc) from exc
    return turn.model_dump(mode="json")


@router.post("/threads/{thread_id}/compact")
async def compact_thread(request: Request, thread_id: str) -> dict[str, Any]:
    mgr = manager(request)
    payload = await body(request)
    req = CompactThreadRequest.model_validate(payload)
    try:
        turn = await mgr.compact_thread(thread_id, req)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    except ValueError as exc:
        raise classify_turn_value_error(exc) from exc
    return turn.model_dump(mode="json")
