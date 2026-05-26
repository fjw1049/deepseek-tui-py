"""POST /v1/user-inputs/{id} — answer or cancel a pending question."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.routes._deps import body, manager

router = APIRouter(prefix="/v1")


@router.get("/user-inputs/pending")
async def list_pending_user_inputs(request: Request) -> list[dict[str, object]]:
    mgr = manager(request)
    thread_id = request.query_params.get("thread_id")
    return await mgr.list_pending_user_inputs(thread_id=thread_id or None)


class UserInputAnswersBody(BaseModel):
    answers: list[dict[str, Any]] = Field(default_factory=list)
    cancelled: bool = False


@router.post("/user-inputs/{request_id}")
@router.post("/user-input/{request_id}")
async def user_input_response(
    request: Request, request_id: str
) -> dict[str, object]:
    mgr = manager(request)
    payload = UserInputAnswersBody.model_validate(await body(request))
    ok = await mgr.resolve_user_input(
        request_id,
        answers=payload.answers if not payload.cancelled else None,
        cancelled=payload.cancelled,
    )
    if not ok:
        raise api_error(
            404, "user input request not found", error="user_input_not_found"
        )
    return {"ok": True}
