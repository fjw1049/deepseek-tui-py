"""Automation HTTP — CRUD, triggers, Feishu inbound."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.runtime_delegate import (
    runtime_from_request,
    unwrap_runtime_result,
)
from deepseek_tui.automation.inbox import append_feishu_inbound, feishu_send_text
from deepseek_tui.automation.pipeline import run_feishu_inbound_agent

router = APIRouter(tags=["automation"])
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
    text: str = "DeepSeek 飞书连接测试"
    receive_id_type: str = "open_id"


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


@router.post("/v1/triggers")
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
    try:
        await feishu_send_text(
            receive_id=body.receive_id.strip(),
            text=body.text.strip() or "DeepSeek 飞书连接测试",
            receive_id_type=body.receive_id_type.strip() or "open_id",
        )
    except Exception as exc:
        raise api_error(502, str(exc), error="feishu_send_failed") from exc
    return {"ok": True}


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
