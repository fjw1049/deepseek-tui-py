"""Authenticated Workbench browser controls; tools use the same service."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deepseek_tui.browser import PREVIEW_THREAD_ID
from deepseek_tui.browser.input import BrowserInput
from deepseek_tui.browser.service import BrowserAction, BrowserActionError, BrowserService

router = APIRouter(prefix="/v1/threads/{thread_id}/browser", tags=["browser"])


def service(request: Request, thread_id: str) -> BrowserService:
    manager = request.app.state.thread_manager
    if thread_id != PREVIEW_THREAD_ID:
        try:
            manager.store.load_thread(thread_id)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(404, "Thread not found") from exc
    return manager.browser_service


@router.get("")
async def state(request: Request, thread_id: str) -> dict[str, Any]:
    return {**service(request, thread_id).state(thread_id),
            **request.app.state.thread_manager.browser_task_state(thread_id)}


class AgentSettingsBody(BaseModel):
    agent_enabled: bool


class RevokeSiteBody(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    site: str = Field(min_length=1, max_length=2048)


@router.get("/settings")
async def browser_settings(request: Request, thread_id: str) -> dict[str, Any]:
    return {**service(request, thread_id).agent_settings(),
            "grants": request.app.state.thread_manager.browser_site_grants()}


@router.post("/settings")
async def set_browser_settings(request: Request, thread_id: str,
                               body: AgentSettingsBody) -> dict[str, Any]:
    try:
        return service(request, thread_id).configure_agent(body.agent_enabled)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/settings/revoke")
async def revoke_browser_site(request: Request, thread_id: str,
                              body: RevokeSiteBody) -> dict[str, Any]:
    service(request, thread_id)
    try:
        request.app.state.thread_manager.revoke_browser_site(body.thread_id, body.site)
        return {"grants": request.app.state.thread_manager.browser_site_grants()}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/frame")
async def frame(request: Request, thread_id: str) -> dict[str, Any]:
    try:
        return {"image": await service(request, thread_id).frame(thread_id)}
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/view")
async def view(request: Request, thread_id: str) -> dict[str, Any]:
    try:
        result = await service(request, thread_id).view(thread_id)
        return {**result, **request.app.state.thread_manager.browser_task_state(thread_id)}
    except (TimeoutError, RuntimeError, ConnectionError) as exc:
        raise HTTPException(503, str(exc) or "Browser is not responding") from exc


@router.post("/input")
async def browser_input(request: Request, thread_id: str, body: BrowserInput) -> dict[str, Any]:
    try:
        return await service(request, thread_id).input(thread_id, body)
    except BrowserActionError as exc:
        raise HTTPException(409, exc.response) from exc
    except (ValueError, TimeoutError, RuntimeError, ConnectionError) as exc:
        raise HTTPException(409, str(exc) or "Browser input failed") from exc


@router.post("/action")
async def action(request: Request, thread_id: str, body: BrowserAction) -> dict[str, Any]:
    browser = service(request, thread_id)
    try:
        if thread_id in browser.runs and body.generation is None:
            raise ValueError("UI browser actions require the current control generation")
        # Opening from the UI starts a user-controlled session.
        if body.action in {"open", "new_tab"} and thread_id not in browser.runs:
            await browser.ensure(thread_id)
            await browser.control(thread_id, "user")
        return await browser.action(thread_id, body, actor="user")
    except BrowserActionError as exc:
        raise HTTPException(409, exc.response) from exc
    except (ValueError, TimeoutError, RuntimeError, ConnectionError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/attach")
async def attach(request: Request, thread_id: str) -> dict[str, Any]:
    """Bind the visible Workbench browser to this thread, under the user's control."""
    browser = service(request, thread_id)
    try:
        await browser.attach_native(thread_id)
        return {**browser.state(thread_id),
                **request.app.state.thread_manager.browser_task_state(thread_id)}
    except (ValueError, TimeoutError, RuntimeError, ConnectionError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/operations/{action_id}")
async def operation(request: Request, thread_id: str, action_id: str) -> dict[str, Any]:
    try:
        return service(request, thread_id).operation(thread_id, action_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


class ControlBody(BaseModel):
    owner: Literal["agent", "user", "stopped"]
    generation: int | None = Field(default=None, ge=0)


class PreferencesBody(BaseModel):
    persistent: bool


class CookieSyncBody(BaseModel):
    action: Literal["enable", "skip", "disable", "sync", "clear"]
    profile: str | None = Field(default=None, max_length=100)
    # Sites to mirror from Chrome; omitted keeps the saved selection.
    sites: list[Annotated[str, Field(min_length=1, max_length=253)]] | None = Field(
        default=None, max_length=2000,
    )
    generation: int | None = Field(default=None, ge=0)


@router.get("/cookie-sync")
async def cookie_sync_state(request: Request, thread_id: str) -> dict[str, Any]:
    from deepseek_tui.browser.chrome_cookies import profiles

    browser = service(request, thread_id)
    return {
        **browser.cookies.state(),
        "profiles": await asyncio.to_thread(profiles),
        "has_saved_cookies": await asyncio.to_thread(browser.cookies.has_saved_cookies),
        "selected_sites": await asyncio.to_thread(browser.cookies.selected_sites),
    }


@router.get("/cookie-sync/sites")
async def cookie_sync_sites(request: Request, thread_id: str, profile: str) -> dict[str, Any]:
    """Sites in a Chrome profile, from host names only; no cookie is decrypted."""
    from deepseek_tui.browser.chrome_cookies import profiles

    browser = service(request, thread_id)
    if profile not in {p["id"] for p in await asyncio.to_thread(profiles)}:
        raise HTTPException(409, "Choose an available Chrome profile")
    result = await browser.cookies.list_source(profile)
    if result.get("error"):
        # "permission": the OS refused the read; "unavailable": anything else.
        error = "permission" if result["error"] == "permission" else "unavailable"
        return {"sites": [], "error": error}
    return result


@router.post("/cookie-sync")
async def cookie_sync(request: Request, thread_id: str, body: CookieSyncBody) -> dict[str, Any]:
    browser = service(request, thread_id)
    try:
        if not browser.preferences(thread_id)["persistent"]:
            raise ValueError("Cookie sync is unavailable in a temporary browser session")
        if body.action == "clear":
            await browser.clear_cookies()
        elif body.action in {"skip", "disable"}:
            browser.cookies.configure("skipped" if body.action == "skip" else "disabled", None)
        else:
            manager = request.app.state.thread_manager
            run = browser.runs.get(thread_id)
            return_to_agent = False
            if run and run.session:
                if run.unresolved:
                    raise ValueError("Resolve pending browser actions before syncing cookies")
                if run.owner != "user":
                    # Syncing must never silently pause a task the agent is running.
                    if manager.browser_task_state(thread_id)["task_running"]:
                        raise ValueError(
                            "The agent is using the browser; take control before syncing cookies"
                        )
                    await manager.control_browser(thread_id, "user", generation=body.generation)
                    return_to_agent = True
            try:
                if body.action == "enable":
                    browser.cookies.configure("enabled", body.profile)
                await browser.sync_cookies(thread_id, body.sites)
            finally:
                if return_to_agent:
                    await manager.control_browser(thread_id, "agent")
        return browser.cookies.state()
    except (ValueError, OSError) as exc:
        # Never include underlying cookie/decryption failures in API errors.
        if isinstance(exc, OSError):
            raise HTTPException(409, "Cookie settings could not be saved") from None
        raise HTTPException(409, str(exc)) from None


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
    from deepseek_tui.browser.skills import install_skill, preview_skill

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
    browser = service(request, thread_id)
    try:
        run = browser.runs.get(thread_id)
        if run:
            await request.app.state.thread_manager.control_browser(
                thread_id, "user", generation=run.generation)
        return await browser.recover(thread_id)
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
    from deepseek_tui.browser.workflows import recording_store

    browser = service(request, thread_id)
    try:
        # Recording IDs are random; the store's path order is not creation order.
        manifests = sorted(recording_store(browser, thread_id).list_recordings(),
                           key=lambda item: item.created_at)
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
    tab_id: str = Field(default="", max_length=200)
    generation: int | None = Field(default=None, ge=0)


@router.post("/workflows")
async def workflow(request: Request, thread_id: str, body: WorkflowBody) -> dict[str, Any]:
    from deepseek_tui.browser.workflows import (
        finish_recording,
        read_workflow,
        start_recording,
        start_replay,
    )

    browser = service(request, thread_id)
    try:
        if body.action == "start":
            return await start_recording(browser, thread_id, tab_id=body.tab_id,
                                         generation=body.generation)
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
        service(request, thread_id)
        return await request.app.state.thread_manager.control_browser(
            thread_id, body.owner, body.generation,
        )
    except (ValueError, RuntimeError, TimeoutError, ConnectionError) as exc:
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


workbench_router = APIRouter(prefix="/v1/browser-workbench", tags=["browser"])


class WorkbenchBridge(BaseModel):
    port: int = Field(ge=1, le=65535)
    token: str = Field(min_length=16, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


@workbench_router.post("")
async def register_workbench(request: Request, body: WorkbenchBridge) -> dict[str, bool]:
    """Workbench announces the loopback bridge to the tabs it shows."""
    request.app.state.thread_manager.browser_service.workbench = body.model_dump()
    return {"success": True}


@workbench_router.delete("")
async def unregister_workbench(request: Request) -> dict[str, bool]:
    request.app.state.thread_manager.browser_service.workbench = None
    return {"success": True}


assistance_router = APIRouter(prefix="/v1/browser-assistance", tags=["browser"])


@assistance_router.get("")
async def pending_assistance(request: Request) -> dict[str, Any]:
    return {"items": request.app.state.thread_manager.pending_browser_assistance()}


class AssistanceResponse(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    choice: Literal["takeover", "continue", "ignore", "information"]
    text: str = Field(default="", max_length=8000)


@router.post("/assistance")
async def respond_assistance(
    request: Request, thread_id: str, body: AssistanceResponse,
) -> dict[str, Any]:
    service(request, thread_id)
    try:
        return await request.app.state.thread_manager.respond_browser_assistance(
            thread_id, body.request_id, body.choice, body.text,
        )
    except (ValueError, RuntimeError, TimeoutError, ConnectionError) as exc:
        raise HTTPException(409, str(exc)) from exc
