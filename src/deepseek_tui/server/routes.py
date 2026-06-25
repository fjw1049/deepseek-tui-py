"""API route handlers.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException


def api_error(status_code: int, message: str, *, error: str | None = None) -> HTTPException:
    body: dict[str, str] = {"message": message}
    if error:
        body["error"] = error
    return HTTPException(status_code=status_code, detail=body)


def runtime_event_payload(record: Any) -> dict[str, object]:
    return {
        "seq": record.seq,
        "timestamp": record.timestamp.isoformat(),
        "thread_id": record.thread_id,
        "turn_id": record.turn_id,
        "item_id": record.item_id,
        "event": record.event,
        "payload": record.payload,
    }


def sse_frame(event_name: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, default=str)
    return f"event: {event_name}\ndata: {data}\n\n"


async def stream_thread_events(
    mgr: Any,
    thread_id: str,
    *,
    since_seq: int | None = None,
    heartbeat_seconds: float = 15.0,
    is_disconnected: Any = None,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Replay backlog then live events from ``event_bus``."""
    queue = mgr.subscribe_events()
    try:
        backlog = mgr.events_since(thread_id, since_seq)
        last_seq = since_seq or 0
        for record in backlog:
            last_seq = max(last_seq, record.seq)
            payload = runtime_event_payload(record)
            yield sse_frame(record.event, payload)

        while True:
            if is_disconnected is not None and await is_disconnected():
                return
            try:
                record = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if record.thread_id != thread_id:
                continue
            if record.seq <= last_seq:
                continue
            last_seq = record.seq
            payload = runtime_event_payload(record)
            yield sse_frame(record.event, payload)
    finally:
        mgr.event_bus.unsubscribe(queue)


def unwrap_runtime_result(result: dict[str, Any]) -> Any:
    """Convert legacy ``{"ok": true, ...}`` envelopes to bare parity JSON."""
    if result.get("ok") is False:
        message = str(result.get("error") or "runtime request failed")
        raise api_error(503, message, error="runtime_error")
    payload = {key: value for key, value in result.items() if key != "ok"}
    return payload


def runtime_from_request(request: Any) -> Any:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise api_error(503, "runtime not configured")
    return runtime


# Shared request helpers + ValueError classifier for runtime_api routes.
from typing import Any

from fastapi import Request

from deepseek_tui.server.threads import RuntimeThreadManager


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


def elevation_bridge(request: Request) -> Any:
    bridge = getattr(request.app.state, "elevation_bridge", None)
    if bridge is None:
        raise api_error(503, "elevation bridge not configured")
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


# POST /v1/approvals/{id} — resolve a pending tool approval.
from fastapi import APIRouter, Request
from pydantic import BaseModel


router_approvals = APIRouter(prefix="/v1")


class DecideApprovalBody(BaseModel):
    decision: str
    remember: bool = False


@router_approvals.get("/approvals/pending")
async def list_pending_approvals(request: Request) -> list[dict[str, object]]:
    bridge = approval_bridge(request)
    thread_id = request.query_params.get("thread_id")
    return bridge.list_pending(thread_id=thread_id or None)


@router_approvals.post("/approvals/{approval_id}")
async def decide_approval(request: Request, approval_id: str) -> dict[str, object]:
    bridge = approval_bridge(request)
    payload = DecideApprovalBody.model_validate(await body(request))
    decision = payload.decision.strip().lower()
    if decision not in {"allow", "deny", "approve", "reject"}:
        raise api_error(400, "decision must be allow or deny", error="invalid_decision")
    approved = decision in {"allow", "approve"}
    if not bridge.resolve(approval_id, approved, remember=payload.remember):
        raise api_error(
            404, f"approval not pending: {approval_id}", error="approval_not_found"
        )
    return {
        "ok": True,
        "approval_id": approval_id,
        "decision": "allow" if approved else "deny",
    }


# Automation HTTP — CRUD, triggers, Feishu inbound.
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field

from deepseek_tui.automation.inbox import (
    append_feishu_inbound,
    default_mail_to_from_config,
    email_send_text,
    feishu_receive_id_type,
    feishu_send_text,
)
from deepseek_tui.automation.pipeline import run_feishu_inbound_agent

router_automation = APIRouter(tags=["automation"])
ingress_router = APIRouter(prefix="/v1/automation", tags=["automation-ingress"])
automations_router = APIRouter(prefix="/v1/automations", tags=["automations"])


class FeishuInboundBody(BaseModel):
    text: str = Field(min_length=1)
    sender_id: str = Field(min_length=1)
    sender_name: str = ""
    chat_id: str = ""
    run_agent: bool = False
    reply_chat_id: str = ""


class FeishuTestSendBody(BaseModel):
    receive_id: str = Field(min_length=1)
    text: str = "DeepSeek Feishu connection test"
    receive_id_type: str | None = None


class EmailTestSendBody(BaseModel):
    to_addr: str | None = None
    subject: str = "DeepSeek email connection test"
    text: str = "This is a test email confirming SMTP works."


class TriggerBody(BaseModel):
    prompt: str = Field(min_length=1)
    digest: dict[str, Any] | None = None
    delivery: dict[str, Any] | None = None
    workspace: str | None = None
    triage_policy: str = "skip"
    triage_metadata: dict[str, Any] | None = None


def _check_webhook_secret(request: Request) -> None:
    expected = os.getenv("DEEPSEEK_FEISHU_WEBHOOK_SECRET", "").strip()
    if not expected:
        return
    auth = request.headers.get("authorization", "")
    header_secret = request.headers.get("x-deepseek-feishu-secret", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    elif header_secret:
        token = header_secret.strip()
    if token != expected:
        raise api_error(401, "invalid feishu webhook secret")


def _map_automation_error(message: str) -> None:
    lowered = message.lower()
    if "not found" in lowered:
        raise api_error(404, message, error="automation_not_found")
    if "not configured" in lowered:
        raise api_error(503, message, error="runtime_error")
    raise api_error(400, message, error="automation_error")


def _unwrap_or_raise(result: dict[str, Any]) -> Any:
    if result.get("ok") is False:
        _map_automation_error(str(result.get("error") or "automation request failed"))
    return unwrap_runtime_result(result)


@router_automation.post("/v1/triggers")
async def post_trigger(
    request: Request,
    body: TriggerBody,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """One-shot webhook/cron-style enqueue (no persisted AutomationRecord)."""
    runtime = runtime_from_request(request)
    payload = _unwrap_or_raise(
        await runtime.fire_trigger(
            {
                "prompt": body.prompt,
                "digest": body.digest,
                "delivery": body.delivery,
                "workspace": body.workspace,
                "triage_policy": body.triage_policy,
                "triage_metadata": body.triage_metadata,
            }
        )
    )
    if body.delivery and payload.get("task_id") and payload.get("delivery") == "scheduled":
        tm = runtime._tool_runtime.task_manager  # noqa: SLF001
        if tm is not None:
            from deepseek_tui.automation.pipeline import deliver_when_task_completes

            tid = str(payload.get("trigger_id", "trigger"))
            background_tasks.add_task(
                deliver_when_task_completes,
                task_id=str(payload["task_id"]),
                task_manager=tm,
                delivery=body.delivery,
                label="trigger",
                label_id=tid,
            )
    return payload


@ingress_router.post("/feishu/inbound")
async def feishu_inbound(
    request: Request,
    body: FeishuInboundBody,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Append inbound line; optionally run agent turn + Feishu reply in background."""
    _check_webhook_secret(request)
    append_feishu_inbound(
        text=body.text,
        sender_id=body.sender_id,
        sender_name=body.sender_name,
        chat_id=body.chat_id,
    )
    if not body.run_agent:
        return {"ok": True, "run_agent": False}

    mgr = getattr(request.app.state, "thread_manager", None)
    if mgr is None:
        raise api_error(503, "thread manager not configured", error="runtime_error")

    async def _run() -> None:
        await run_feishu_inbound_agent(
            thread_manager=mgr,
            text=body.text,
            sender_id=body.sender_id,
            sender_name=body.sender_name,
            chat_id=body.chat_id,
            reply_chat_id=body.reply_chat_id or body.chat_id or body.sender_id,
        )

    background_tasks.add_task(_run)
    return {"ok": True, "run_agent": True, "status": "started"}


@ingress_router.post("/feishu/test-send")
async def feishu_test_send(body: FeishuTestSendBody) -> dict[str, Any]:
    """Send a short text to verify ``[automation.feishu]`` in config.toml."""
    rid_type = (
        body.receive_id_type.strip()
        if body.receive_id_type and body.receive_id_type.strip()
        else feishu_receive_id_type(body.receive_id)
    )
    try:
        await feishu_send_text(
            receive_id=body.receive_id.strip(),
            text=body.text.strip() or "DeepSeek Feishu connection test",
            receive_id_type=rid_type,
        )
    except Exception as exc:
        raise api_error(502, str(exc), error="feishu_send_failed") from exc
    return {"ok": True}


@ingress_router.post("/email/test-send")
async def email_test_send(body: EmailTestSendBody) -> dict[str, Any]:
    """Send a short message to verify ``[automation.email]`` SMTP settings."""
    to_addr = (body.to_addr or default_mail_to_from_config() or "").strip()
    if not to_addr:
        raise api_error(
            400,
            "Recipient address is required (set automation.mail_to or pass to_addr).",
            error="email_recipient_missing",
        )
    try:
        await email_send_text(
            to_addr=to_addr,
            subject=body.subject.strip() or "DeepSeek email connection test",
            body=body.text.strip() or "This is a test email confirming SMTP works.",
        )
    except Exception as exc:
        raise api_error(502, str(exc), error="email_send_failed") from exc
    return {"ok": True, "to": to_addr}


@automations_router.get("")
async def list_automations(request: Request) -> list[dict[str, Any]]:
    runtime = runtime_from_request(request)
    payload = _unwrap_or_raise(await runtime.list_automations())
    return payload.get("automations", [])


@automations_router.post("", status_code=201)
async def create_automation(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise api_error(400, "JSON object required")
    payload = _unwrap_or_raise(await runtime.create_automation(body))
    automation = payload.get("automation")
    if not isinstance(automation, dict):
        raise api_error(500, "invalid create response")
    return automation


@automations_router.get("/{automation_id}")
async def get_automation(request: Request, automation_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    payload = _unwrap_or_raise(await runtime.get_automation(automation_id))
    automation = payload.get("automation")
    if not isinstance(automation, dict):
        raise api_error(404, f"automation not found: {automation_id}", error="automation_not_found")
    return automation


@automations_router.patch("/{automation_id}")
async def update_automation(request: Request, automation_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise api_error(400, "JSON object required")
    payload = _unwrap_or_raise(await runtime.update_automation(automation_id, body))
    automation = payload.get("automation")
    if not isinstance(automation, dict):
        raise api_error(500, "invalid update response")
    return automation


@automations_router.delete("/{automation_id}")
async def delete_automation(request: Request, automation_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    payload = _unwrap_or_raise(await runtime.delete_automation(automation_id))
    automation = payload.get("automation")
    if not isinstance(automation, dict):
        raise api_error(500, "invalid delete response")
    return automation


@automations_router.post("/{automation_id}/run")
async def run_automation(request: Request, automation_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    payload = _unwrap_or_raise(await runtime.run_automation(automation_id))
    run = payload.get("run")
    if not isinstance(run, dict):
        raise api_error(500, "invalid run response")
    return run


@automations_router.post("/{automation_id}/pause")
async def pause_automation(request: Request, automation_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    payload = _unwrap_or_raise(await runtime.pause_automation(automation_id))
    automation = payload.get("automation")
    if not isinstance(automation, dict):
        raise api_error(500, "invalid pause response")
    return automation


@automations_router.post("/{automation_id}/resume")
async def resume_automation(request: Request, automation_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    payload = _unwrap_or_raise(await runtime.resume_automation(automation_id))
    automation = payload.get("automation")
    if not isinstance(automation, dict):
        raise api_error(500, "invalid resume response")
    return automation


@automations_router.get("/{automation_id}/runs")
async def list_automation_runs(
    request: Request,
    automation_id: str,
) -> list[dict[str, Any]]:
    runtime = runtime_from_request(request)
    limit_str = request.query_params.get("limit")
    limit = int(limit_str) if limit_str else None
    payload = _unwrap_or_raise(await runtime.list_automation_runs(automation_id, limit=limit))
    return payload.get("runs", [])


# POST /v1/elevations/{id} — resolve a pending sandbox elevation (L3).
from fastapi import APIRouter, Request
from pydantic import BaseModel


router_elevations = APIRouter(prefix="/v1")


class DecideElevationBody(BaseModel):
    decision: str


@router_elevations.get("/elevations/pending")
async def list_pending_elevations(request: Request) -> list[dict[str, object]]:
    bridge = elevation_bridge(request)
    thread_id = request.query_params.get("thread_id")
    return bridge.list_pending(thread_id=thread_id or None)


@router_elevations.post("/elevations/{elevation_id}")
async def decide_elevation(request: Request, elevation_id: str) -> dict[str, object]:
    bridge = elevation_bridge(request)
    payload = DecideElevationBody.model_validate(await body(request))
    decision = payload.decision.strip().lower()
    if decision not in {"allow", "deny", "approve", "reject", "elevate"}:
        raise api_error(400, "decision must be allow or deny", error="invalid_decision")
    approved = decision in {"allow", "approve", "elevate"}
    if not bridge.resolve(elevation_id, approved):
        raise api_error(
            404,
            f"elevation not pending: {elevation_id}",
            error="elevation_not_found",
        )
    return {
        "ok": True,
        "elevation_id": elevation_id,
        "decision": "allow" if approved else "deny",
    }


# GET /v1/threads/{id}/events — long-lived SSE with backlog replay.
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse


router_events = APIRouter(prefix="/v1")


@router_events.get("/threads/{thread_id}/events")
async def stream_events(request: Request, thread_id: str) -> StreamingResponse:
    mgr = manager(request)
    try:
        await mgr.get_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    since_str = request.query_params.get("since_seq")
    since_seq: int | None = None
    if since_str:
        try:
            since_seq = int(since_str)
        except ValueError as exc:
            raise api_error(
                400,
                f"since_seq must be a non-negative integer, got {since_str!r}",
                error="invalid_since_seq",
            ) from exc
        if since_seq < 0:
            raise api_error(
                400,
                "since_seq must be >= 0",
                error="invalid_since_seq",
            )
    generator = stream_thread_events(
        mgr,
        thread_id,
        since_seq=since_seq,
        is_disconnected=request.is_disconnected,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


# GET /health and /healthz — connection probes.
from fastapi import APIRouter, Request

router_health = APIRouter()


@router_health.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "deepseek-runtime-api", "mode": "local"}


@router_health.get("/healthz")
async def healthz_alias() -> dict[str, str]:
    return {"status": "ok", "service": "deepseek-runtime-api", "mode": "local"}


@router_health.get("/health/ready")
async def health_ready(request: Request) -> dict[str, object]:
    """Readiness probe — HTTP is up; MCP may still be warming in background."""

    runtime = runtime_from_request(request)
    mcp = runtime.mcp_preload_status()
    warming = bool(mcp.get("warming"))
    return {
        "status": "ok",
        "service": "deepseek-runtime-api",
        "ready": not warming,
        "mcp": mcp,
    }


# GET /v1/jobs — shell + durable task snapshot for Workbench.
from fastapi import APIRouter, Request


router_jobs = APIRouter(prefix="/v1")


@router_jobs.get("/jobs")
async def list_jobs(request: Request) -> dict[str, object]:
    thread_id = request.query_params.get("thread_id")
    mgr = manager(request)
    return await mgr.jobs_snapshot(thread_id=thread_id or None)


# POST /v1/mcp/startup — start enabled MCP servers (Workbench Settings reload).
#
# The Workbench reloads MCP config from disk then asks the runtime to (re)connect
# its enabled servers. The legacy router exposed this under ``/legacy/mcp/startup``
# only; the GUI talks exclusively to ``/v1/*`` so the parity route lives here.
#
from typing import Any

from fastapi import APIRouter, Request


router_mcp = APIRouter(prefix="/v1")


@router_mcp.post("/mcp/startup")
async def mcp_startup(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    return await runtime.mcp_startup()


@router_mcp.get("/mcp/preload-status")
async def mcp_preload_status(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    return runtime.mcp_preload_status()


# GET /v1/sessions + export Workbench threads back to TUI session files.
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from deepseek_tui.server.sessions import (
    export_thread_to_tui_session,
    list_unified_sessions,
)
from deepseek_tui.config.paths import user_sessions_dir

router_sessions = APIRouter(prefix="/v1")


@router_sessions.get("/sessions")
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


@router_sessions.post("/threads/{thread_id}/export-session")
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


# GET /v1/skills — discovered skills for Workbench settings/diagnostics.
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from deepseek_tui.integrations.skills import discover_in_workspace

router_skills = APIRouter(prefix="/v1")


@router_skills.get("/skills")
async def list_skills(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    workspace = request.query_params.get("workspace")
    wd = (
        Path(workspace).expanduser().resolve()
        if workspace
        else runtime.working_directory
    )
    skills_dir = Path(runtime.config.skills_dir).expanduser()
    try:
        registry = discover_in_workspace(skills_dir=skills_dir, workspace=wd)
    except (OSError, ValueError) as exc:
        raise api_error(503, f"skill discovery failed: {exc}", error="skills_unavailable") from exc
    return {
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "path": str(skill.path),
            }
            for skill in registry.skills
        ],
        "warnings": registry.warnings,
    }


# GET/POST /v1/tasks — durable background task queue.
from typing import Any

from fastapi import APIRouter, Request


router_tasks = APIRouter(prefix="/v1")


@router_tasks.get("/tasks")
async def list_tasks(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    limit_str = request.query_params.get("limit")
    limit = int(limit_str) if limit_str else None
    payload = unwrap_runtime_result(await runtime.list_tasks(limit=limit))
    return {"tasks": payload.get("tasks", [])}


@router_tasks.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    payload = unwrap_runtime_result(await runtime.get_task(task_id))
    task = payload.get("task")
    if not isinstance(task, dict):
        raise api_error(404, f"task not found: {task_id}", error="task_not_found")
    return task


@router_tasks.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    payload = unwrap_runtime_result(await runtime.cancel_task(task_id))
    task = payload.get("task")
    if not isinstance(task, dict):
        raise api_error(404, f"task not found: {task_id}", error="task_not_found")
    return task


# /v1/threads CRUD + summary + fork + resume.
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from deepseek_tui.server.threads import (
    CreateThreadRequest,
    UpdateThreadRequest,
)
from deepseek_tui.server.sessions import ImportTuiSessionRequest

router_threads = APIRouter(prefix="/v1")


@router_threads.get("/usage")
async def thread_usage(request: Request) -> dict[str, Any]:
    mgr = manager(request)
    group_by = request.query_params.get("group_by", "runtime")
    if group_by == "model":
        scope = request.query_params.get("scope", "session")
        if scope != "session":
            raise api_error(
                400,
                f"unsupported usage scope: {scope}",
                error="validation_error",
            )
        try:
            return await mgr.get_session_model_usage(scope=scope)
        except ValueError as exc:
            raise api_error(400, str(exc), error="validation_error") from exc
    if group_by != "thread":
        raise api_error(
            400,
            f"unsupported usage grouping: {group_by}",
            error="validation_error",
        )
    thread_id = (request.query_params.get("thread_id") or "").strip()
    if not thread_id:
        raise api_error(
            400,
            "thread_id is required when group_by=thread",
            error="validation_error",
        )
    try:
        return await mgr.get_thread_usage(thread_id, group_by=group_by)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    except ValueError as exc:
        raise api_error(400, str(exc), error="validation_error") from exc


@router_threads.get("/threads")
async def list_threads(request: Request) -> list[dict[str, Any]]:
    mgr = manager(request)
    include_archived = request.query_params.get("include_archived", "false") == "true"
    limit_str = request.query_params.get("limit")
    limit = int(limit_str) if limit_str else None
    threads = await mgr.list_threads(include_archived=include_archived, limit=limit)
    return [t.model_dump(mode="json") for t in threads]


@router_threads.post("/threads", status_code=201)
async def create_thread(request: Request) -> JSONResponse:
    mgr = manager(request)
    payload = await body(request)
    req = CreateThreadRequest.model_validate(payload)
    thread = await mgr.create_thread(req)
    return JSONResponse(status_code=201, content=thread.model_dump(mode="json"))


@router_threads.post("/threads/import-session", status_code=201)
async def import_tui_session(request: Request) -> JSONResponse:
    mgr = manager(request)
    payload = await body(request)
    req = ImportTuiSessionRequest.model_validate(payload)
    try:
        thread = await mgr.import_tui_session(req)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="session_not_found") from exc
    except ValueError as exc:
        raise api_error(400, str(exc), error="invalid_session") from exc
    return JSONResponse(status_code=201, content=thread.model_dump(mode="json"))


@router_threads.get("/threads/summary")
async def threads_summary(request: Request) -> dict[str, Any]:
    mgr = manager(request)
    return await mgr.threads_summary()


@router_threads.get("/threads/{thread_id}/active")
async def thread_turn_active(request: Request, thread_id: str) -> dict[str, bool]:
    mgr = manager(request)
    try:
        active = await mgr.is_thread_turn_active(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    return {"active": active}


@router_threads.post("/threads/{thread_id}/warmup")
async def warmup_thread(request: Request, thread_id: str) -> dict[str, Any]:
    mgr = manager(request)
    try:
        return await mgr.warmup_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc


@router_threads.get("/threads/{thread_id}")
async def get_thread_detail(request: Request, thread_id: str) -> dict[str, Any]:
    mgr = manager(request)
    try:
        detail = await mgr.get_thread_detail(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    return detail.model_dump(mode="json")


@router_threads.get("/threads/{thread_id}/context")
async def get_thread_context(request: Request, thread_id: str) -> dict[str, int]:
    """Token budget breakdown (TUI ``/context`` parity)."""
    mgr = manager(request)
    try:
        return await mgr.get_thread_context_breakdown(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc


@router_threads.patch("/threads/{thread_id}")
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


@router_threads.post("/threads/{thread_id}/fork", status_code=201)
async def fork_thread(request: Request, thread_id: str) -> JSONResponse:
    mgr = manager(request)
    try:
        forked = await mgr.fork_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    return JSONResponse(status_code=201, content=forked.model_dump(mode="json"))


@router_threads.post("/threads/{thread_id}/resume")
async def resume_thread(request: Request, thread_id: str) -> dict[str, Any]:
    mgr = manager(request)
    try:
        detail = await mgr.resume_thread(thread_id)
    except FileNotFoundError as exc:
        raise api_error(404, str(exc), error="thread_not_found") from exc
    return detail.model_dump(mode="json")


# /v1/threads/{id}/turns lifecycle: start / interrupt / steer / compact.
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from deepseek_tui.server.threads import (
    CompactThreadRequest,
    StartTurnRequest,
    SteerTurnRequest,
)

router_turns = APIRouter(prefix="/v1")


@router_turns.post("/threads/{thread_id}/turns", status_code=201)
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


@router_turns.post("/threads/{thread_id}/turns/{turn_id}/interrupt")
async def interrupt_turn(
    request: Request, thread_id: str, turn_id: str
) -> dict[str, Any]:
    mgr = manager(request)
    try:
        turn = await mgr.interrupt_turn(thread_id, turn_id)
    except ValueError as exc:
        raise classify_turn_value_error(exc) from exc
    return turn.model_dump(mode="json")


@router_turns.post("/threads/{thread_id}/turns/{turn_id}/steer")
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


@router_turns.post("/threads/{thread_id}/compact")
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


# POST /v1/user-inputs/{id} — answer or cancel a pending question.
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field


router_user_inputs = APIRouter(prefix="/v1")


@router_user_inputs.get("/user-inputs/pending")
async def list_pending_user_inputs(request: Request) -> list[dict[str, object]]:
    mgr = manager(request)
    thread_id = request.query_params.get("thread_id")
    return await mgr.list_pending_user_inputs(thread_id=thread_id or None)


class UserInputAnswersBody(BaseModel):
    answers: list[dict[str, Any]] = Field(default_factory=list)
    cancelled: bool = False


@router_user_inputs.post("/user-inputs/{request_id}")
@router_user_inputs.post("/user-input/{request_id}")
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


# GET /v1/workspace/status — diagnostic dialog.
from typing import Any

from fastapi import APIRouter, Request


router_workspace = APIRouter(prefix="/v1")


@router_workspace.get("/workspace/status")
async def workspace_status(request: Request) -> dict[str, Any]:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise api_error(503, "runtime not configured")
    return await runtime.workspace_status()
"""Rust-parity /v1 runtime routes for DeepSeek Workbench.

Routes are split by domain (health/threads/turns/events/approvals/user_inputs/
workspace) to keep each file under ~80 LOC. ``build_runtime_api_router``
assembles them so the public surface seen by ``attach_runtime_api`` is
unchanged.
"""


from fastapi import APIRouter

__all__ = ["build_runtime_api_router"]


def build_runtime_api_router() -> APIRouter:
    """Build the combined runtime API router."""
    router = APIRouter()
    router.include_router(router_approvals)
    router.include_router(router_automation)
    router.include_router(router_elevations)
    router.include_router(router_events)
    router.include_router(router_health)
    router.include_router(router_jobs)
    router.include_router(router_mcp)
    router.include_router(router_sessions)
    router.include_router(router_skills)
    router.include_router(router_tasks)
    router.include_router(router_threads)
    router.include_router(router_turns)
    router.include_router(router_user_inputs)
    router.include_router(router_workspace)
    router.include_router(ingress_router)
    router.include_router(automations_router)
    return router