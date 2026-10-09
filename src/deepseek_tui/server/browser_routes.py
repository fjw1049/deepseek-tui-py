"""Authenticated Workbench browser controls; tools use the same service."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

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


class PreferencesBody(BaseModel):
    persistent: bool


@router.get("/environment")
async def environment(request: Request, thread_id: str) -> dict[str, Any]:
    return service(request, thread_id).environment()


@router.get("/installation")
async def installation_status(request: Request, thread_id: str) -> dict[str, Any]:
    return service(request, thread_id).installer.state


class InstallationBody(BaseModel):
    action: Literal["start", "stop"] = "start"


@router.post("/installation")
async def install_browser(
    request: Request, thread_id: str, body: InstallationBody
) -> dict[str, Any]:
    installer = service(request, thread_id).installer
    if body.action == "stop":
        await installer.close()
        return installer.state
    return installer.start()


class SkillBody(BaseModel):
    action: Literal["preview", "install"]
    recording_id: str = Field(max_length=100)
    name: str = Field(min_length=1, max_length=63)
    description: str = Field(min_length=1, max_length=500)
    digest: str = Field(default="", max_length=64)


@router.post("/skills")
async def workflow_skill(request: Request, thread_id: str, body: SkillBody) -> dict[str, Any]:
    from deepseek_tui.browser_skills import install_skill, preview_skill

    browser = service(request, thread_id)
    args = (browser, thread_id, body.recording_id, body.name, body.description)
    try:
        if body.action == "preview":
            return await asyncio.to_thread(preview_skill, *args)
        thread = request.app.state.thread_manager.store.load_thread(thread_id)
        return await asyncio.to_thread(install_skill, *args, body.digest, Path(thread.workspace))
    except (ValueError, OSError, ImportError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/preferences")
async def preferences(request: Request, thread_id: str) -> dict[str, Any]:
    return service(request, thread_id).preferences(thread_id)


@router.post("/preferences")
async def configure(request: Request, thread_id: str, body: PreferencesBody) -> dict[str, Any]:
    try:
        return service(request, thread_id).configure(thread_id, body.persistent)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/recover")
async def recover(request: Request, thread_id: str) -> dict[str, Any]:
    try:
        return await service(request, thread_id).recover(thread_id)
    except (ValueError, RuntimeError, TimeoutError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/clear-profile")
async def clear_profile(request: Request, thread_id: str) -> dict[str, bool]:
    try:
        service(request, thread_id).clear_profile(thread_id)
        return {"success": True}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/workflows")
async def workflows(request: Request, thread_id: str) -> dict[str, Any]:
    from deepseek_tui.browser_workflows import recording_store

    browser = service(request, thread_id)
    try:
        manifests = recording_store(browser, thread_id).list_recordings()
        return {
            "items": [
                {"id": item.recording_id, "steps": item.stats.steps, "status": item.status}
                for item in manifests[-20:][::-1]
            ]
        }
    except ImportError:
        return {"items": []}


class WorkflowBody(BaseModel):
    action: Literal["start", "stop", "preview", "replay"]
    recording_id: str = ""
    inputs: dict[str, str] = {}


@router.post("/workflows")
async def workflow(request: Request, thread_id: str, body: WorkflowBody) -> dict[str, Any]:
    from deepseek_tui.browser_workflows import (
        finish_recording,
        read_workflow,
        start_recording,
        start_replay,
    )

    browser = service(request, thread_id)
    try:
        if body.action == "start":
            return await start_recording(browser, thread_id)
        if body.action == "stop":
            run = browser.runs.get(thread_id)
            if not run:
                raise ValueError("No browser session")
            async with run.lock:
                return await finish_recording(run)
        if body.action == "preview":
            return read_workflow(browser, thread_id, body.recording_id).model_dump(by_alias=True)
        return await start_replay(browser, thread_id, body.recording_id, body.inputs)
    except (ValueError, RuntimeError, TimeoutError, FileNotFoundError, ImportError) as exc:
        raise HTTPException(409, str(exc)) from exc


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
        mime = {".gif": "image/gif", ".jpg": "image/jpeg", ".webm": "video/webm"}[path.suffix]
        return {"image": f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/export")
async def export_evidence(request: Request, thread_id: str) -> dict[str, str]:
    try:
        path = service(request, thread_id).export_evidence(thread_id)
        return {"path": str(path)}
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
