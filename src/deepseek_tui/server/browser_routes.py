"""Authenticated Workbench browser controls; tools use the same service."""

from __future__ import annotations

import base64
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from deepseek_tui.browser import BrowserAction, BrowserService

router = APIRouter(prefix="/v1/threads/{thread_id}/browser", tags=["browser"])


def service(request: Request, thread_id: str) -> BrowserService:
    manager = request.app.state.thread_manager
    try:
        manager.store.load_thread(thread_id)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise HTTPException(404, "Thread not found") from exc
    return manager.browser_service


@router.get("")
async def state(request: Request, thread_id: str) -> dict[str, Any]:
    return service(request, thread_id).state(thread_id)


@router.get("/frame")
async def frame(request: Request, thread_id: str) -> dict[str, Any]:
    try:
        return {"image": await service(request, thread_id).frame(thread_id)}
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/action")
async def action(request: Request, thread_id: str, body: BrowserAction) -> dict[str, Any]:
    browser = service(request, thread_id)
    try:
        # Opening from the UI starts a user-controlled session.
        if body.action == "open" and not browser.state(thread_id)["active"]:
            await browser.ensure(thread_id)
            await browser.control(thread_id, "user")
        return await browser.action(thread_id, body, actor="user")
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(409, str(exc)) from exc


class ControlBody(BaseModel):
    owner: Literal["agent", "user", "stopped"]


@router.post("/control")
async def control(request: Request, thread_id: str, body: ControlBody) -> dict[str, Any]:
    try:
        return await service(request, thread_id).control(thread_id, body.owner)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/demo")
async def demo(request: Request, thread_id: str) -> dict[str, Any]:
    try:
        return await service(request, thread_id).start_demo(thread_id)
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/artifacts/{name}")
async def artifact(request: Request, thread_id: str, name: str) -> dict[str, str]:
    try:
        path = service(request, thread_id).artifact(thread_id, name)
        mime = "image/gif" if path.suffix == ".gif" else "image/jpeg"
        return {"image": f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
