"""Rust-parity /v1 runtime routes for DeepSeek Workbench."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.sse import stream_thread_events
from deepseek_tui.app_server.runtime_threads import (
    CompactThreadRequest,
    CreateThreadRequest,
    StartTurnRequest,
    SteerTurnRequest,
    UpdateThreadRequest,
)
from deepseek_tui.app_server.thread_manager import RuntimeThreadManager


class DecideApprovalBody(BaseModel):
    decision: str
    remember: bool = False


class UserInputAnswersBody(BaseModel):
    answers: list[dict[str, Any]] = Field(default_factory=list)
    cancelled: bool = False


def build_runtime_api_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "deepseek-runtime-api", "mode": "local"}

    @router.get("/healthz")
    async def healthz_alias() -> dict[str, str]:
        return {"status": "ok", "protocol": "v2", "service": "deepseek-app-server"}

    v1 = APIRouter(prefix="/v1")

    @v1.get("/threads")
    async def list_threads(request: Request) -> list[dict[str, Any]]:
        manager = _manager(request)
        include_archived = request.query_params.get("include_archived", "false") == "true"
        limit_str = request.query_params.get("limit")
        limit = int(limit_str) if limit_str else None
        threads = await manager.list_threads(include_archived=include_archived, limit=limit)
        return [t.model_dump(mode="json") for t in threads]

    @v1.post("/threads", status_code=201)
    async def create_thread(request: Request) -> JSONResponse:
        manager = _manager(request)
        payload = await _body(request)
        req = CreateThreadRequest.model_validate(payload)
        thread = await manager.create_thread(req)
        return JSONResponse(
            status_code=201,
            content=thread.model_dump(mode="json"),
        )

    @v1.get("/threads/summary")
    async def threads_summary(request: Request) -> dict[str, Any]:
        manager = _manager(request)
        return await manager.threads_summary()

    @v1.get("/threads/{thread_id}")
    async def get_thread_detail(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _manager(request)
        try:
            detail = await manager.get_thread_detail(thread_id)
        except FileNotFoundError as exc:
            raise api_error(404, str(exc), error="thread_not_found") from exc
        return detail.model_dump(mode="json")

    @v1.patch("/threads/{thread_id}")
    async def update_thread(
        request: Request, thread_id: str
    ) -> dict[str, Any]:
        manager = _manager(request)
        payload = await _body(request)
        req = UpdateThreadRequest.model_validate(payload)
        try:
            thread = await manager.update_thread(thread_id, req)
        except FileNotFoundError as exc:
            raise api_error(404, str(exc), error="thread_not_found") from exc
        except ValueError as exc:
            raise api_error(400, str(exc), error="invalid_request") from exc
        return thread.model_dump(mode="json")

    @v1.delete("/threads/{thread_id}")
    async def delete_thread(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _manager(request)
        try:
            thread = await manager.update_thread(
                thread_id, UpdateThreadRequest(archived=True)
            )
        except FileNotFoundError as exc:
            raise api_error(404, str(exc), error="thread_not_found") from exc
        return thread.model_dump(mode="json")

    @v1.post("/threads/{thread_id}/fork", status_code=201)
    async def fork_thread(request: Request, thread_id: str) -> JSONResponse:
        manager = _manager(request)
        try:
            forked = await manager.fork_thread(thread_id)
        except FileNotFoundError as exc:
            raise api_error(404, str(exc), error="thread_not_found") from exc
        return JSONResponse(status_code=201, content=forked.model_dump(mode="json"))

    @v1.post("/threads/{thread_id}/resume")
    async def resume_thread(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _manager(request)
        try:
            detail = await manager.resume_thread(thread_id)
        except FileNotFoundError as exc:
            raise api_error(404, str(exc), error="thread_not_found") from exc
        return detail.model_dump(mode="json")

    @v1.post("/threads/{thread_id}/turns", status_code=201)
    async def start_turn(
        request: Request, thread_id: str
    ) -> JSONResponse:
        manager = _manager(request)
        payload = await _body(request)
        req = StartTurnRequest.model_validate(payload)
        try:
            turn = await manager.start_turn(thread_id, req)
            thread = await manager.get_thread(thread_id)
        except FileNotFoundError as exc:
            raise api_error(404, str(exc), error="thread_not_found") from exc
        except ValueError as exc:
            raise api_error(409, str(exc), error="turn_conflict") from exc
        return JSONResponse(
            status_code=201,
            content={
                "thread": thread.model_dump(mode="json"),
                "turn": turn.model_dump(mode="json"),
            },
        )

    @v1.post("/threads/{thread_id}/turns/{turn_id}/interrupt")
    async def interrupt_turn(
        request: Request, thread_id: str, turn_id: str
    ) -> dict[str, Any]:
        manager = _manager(request)
        try:
            turn = await manager.interrupt_turn(thread_id, turn_id)
        except ValueError as exc:
            raise api_error(409, str(exc), error="turn_not_active") from exc
        return turn.model_dump(mode="json")

    @v1.post("/threads/{thread_id}/turns/{turn_id}/steer")
    async def steer_turn(
        request: Request, thread_id: str, turn_id: str
    ) -> dict[str, Any]:
        manager = _manager(request)
        payload = await _body(request)
        req = SteerTurnRequest.model_validate(payload)
        try:
            turn = await manager.steer_turn(thread_id, turn_id, req)
        except ValueError as exc:
            raise api_error(409, str(exc), error="turn_not_active") from exc
        return turn.model_dump(mode="json")

    @v1.post("/threads/{thread_id}/compact")
    async def compact_thread(request: Request, thread_id: str) -> dict[str, Any]:
        manager = _manager(request)
        payload = await _body(request)
        req = CompactThreadRequest.model_validate(payload)
        try:
            turn = await manager.compact_thread(thread_id, req)
        except FileNotFoundError as exc:
            raise api_error(404, str(exc), error="thread_not_found") from exc
        except ValueError as exc:
            raise api_error(409, str(exc), error="turn_conflict") from exc
        return turn.model_dump(mode="json")

    @v1.get("/threads/{thread_id}/events")
    async def stream_events(request: Request, thread_id: str) -> StreamingResponse:
        manager = _manager(request)
        try:
            await manager.get_thread(thread_id)
        except FileNotFoundError as exc:
            raise api_error(404, str(exc), error="thread_not_found") from exc
        since_str = request.query_params.get("since_seq")
        since_seq = int(since_str) if since_str else None
        generator = stream_thread_events(manager, thread_id, since_seq)
        return StreamingResponse(generator, media_type="text/event-stream")

    @v1.post("/approvals/{approval_id}")
    async def decide_approval(
        request: Request, approval_id: str
    ) -> dict[str, object]:
        bridge = _approval_bridge(request)
        body = DecideApprovalBody.model_validate(await _body(request))
        decision = body.decision.strip().lower()
        if decision not in {"allow", "deny", "approve", "reject"}:
            raise api_error(400, "decision must be allow or deny", error="invalid_decision")
        approved = decision in {"allow", "approve"}
        if not bridge.resolve(approval_id, approved):
            raise api_error(404, f"approval not pending: {approval_id}", error="not_found")
        return {"ok": True, "approval_id": approval_id, "decision": "allow" if approved else "deny"}

    @v1.post("/user-inputs/{request_id}")
    @v1.post("/user-input/{request_id}")
    async def user_input_response(
        request: Request, request_id: str
    ) -> dict[str, object]:
        manager = _manager(request)
        body = UserInputAnswersBody.model_validate(await _body(request))
        ok = await manager.resolve_user_input(
            request_id,
            answers=body.answers if not body.cancelled else None,
            cancelled=body.cancelled,
        )
        if not ok:
            raise api_error(404, "user input request not found", error="not_found")
        return {"ok": True}

    @v1.get("/workspace/status")
    async def workspace_status(request: Request) -> dict[str, Any]:
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is None:
            raise api_error(503, "runtime not configured")
        return await runtime.workspace_status()

    router.include_router(v1)
    return router


def _manager(request: Request) -> RuntimeThreadManager:
    manager = getattr(request.app.state, "thread_manager", None)
    if manager is None:
        raise api_error(503, "runtime thread manager not configured")
    return manager


def _approval_bridge(request: Request) -> Any:
    bridge = getattr(request.app.state, "approval_bridge", None)
    if bridge is None:
        raise api_error(503, "approval bridge not configured")
    return bridge


async def _body(request: Request) -> dict[str, Any]:
    if request.headers.get("content-length", "0") == "0":
        return {}
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
