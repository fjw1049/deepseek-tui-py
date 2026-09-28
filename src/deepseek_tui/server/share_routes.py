"""Local runtime bridge to the hosted service or an optional self-hosted origin."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deepseek_tui.config.paths import user_deepseek_dir
from deepseek_tui.server.session_snapshot import (
    MAX_SNAPSHOT_BYTES,
    SessionSnapshot,
    build_snapshot,
    git,
    import_snapshot,
    restore_project,
    validate_snapshot,
)
from deepseek_tui.utils import read_json_or_none, write_json_atomic

router = APIRouter(prefix="/v1/sharing")
DEFAULT_SERVICE_URL = "https://deepseek-workbench-shares.major-emu-7913.chatgpt.site"


class ShareSettings(BaseModel):
    service_url: str
    upload_key: str | None = None


class CreateShare(BaseModel):
    thread_id: str
    include_project: bool = False
    expires_in_days: int = Field(default=7, ge=1, le=30)


class ShareLink(BaseModel):
    url: str


class RestoreShare(ShareLink):
    workspace: str | None = None
    restore_project: bool = True


def settings_path() -> Path:
    return user_deepseek_dir() / "sharing.json"


def settings() -> dict:
    value = read_json_or_none(settings_path()) or {}
    if not value.get("service_url"):
        value["service_url"] = DEFAULT_SERVICE_URL
    return value


def service_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise HTTPException(400, "Enter a service origin, for example https://shares.example.com")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(400, "Remote share services require HTTPS")
    return value.strip().rstrip("/")


def configured() -> tuple[str, str]:
    config = settings()
    if not config.get("service_url"):
        raise HTTPException(400, "Configure a share service first")
    return service_url(config["service_url"]), config.get("upload_key", "")


def token_from_link(link: str, origin: str) -> str:
    parsed = urlsplit(link.strip())
    if f"{parsed.scheme}://{parsed.netloc}" != origin or parsed.query or parsed.fragment:
        raise HTTPException(400, "Link must belong to your configured share service")
    match = re.fullmatch(r"/s/([A-Za-z0-9_-]{43})", parsed.path)
    if not match:
        raise HTTPException(400, "Invalid share link")
    return match.group(1)


async def remote(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    auth: bool = False,
    read_origin: str | None = None,
    delete_key: str | None = None,
):
    # A pasted link supplies its own read-only origin. Never send credentials to it.
    if read_origin is not None:
        if auth or method != "GET":
            raise ValueError("External share links are read-only")
        origin, key = service_url(read_origin), ""
    else:
        origin, key = configured()
    managed = origin == DEFAULT_SERVICE_URL
    if delete_key is not None:
        origin, key = DEFAULT_SERVICE_URL, delete_key
    if auth and not key and not (managed and method == "POST"):
        raise HTTPException(400, "Configure an upload key to create or revoke shares")
    headers = {"Authorization": f"Bearer {key}"} if auth and key else {}
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                method, origin + path, json=payload, headers=headers
            ) as response:
                if response.status_code >= 300:
                    raise HTTPException(
                        response.status_code
                        if response.status_code in {401, 403, 404, 410, 413, 429}
                        else 502,
                        f"Share service returned {response.status_code}",
                    )
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_SNAPSHOT_BYTES + 4096:
                        raise HTTPException(413, "Snapshot is too large")
                return json.loads(data) if data else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Cannot read share service response") from exc


async def download(link: str) -> tuple[str, SessionSnapshot]:
    parsed = urlsplit(link.strip())
    origin = service_url(f"{parsed.scheme}://{parsed.netloc}")
    token = token_from_link(link, origin)
    data = await remote("GET", f"/v1/shares/{token}", read_origin=origin)
    try:
        snapshot = SessionSnapshot.model_validate(data["snapshot"])
        validate_snapshot(snapshot)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, "Invalid or unsupported session snapshot") from exc
    return token, snapshot


@router.get("/settings")
async def get_settings():
    config = settings()
    return {
        "service_url": config.get("service_url", ""),
        "has_upload_key": bool(config.get("upload_key")),
        "ready": bool(config.get("service_url") == DEFAULT_SERVICE_URL or config.get("upload_key")),
    }


@router.put("/settings")
async def save_settings(req: ShareSettings):
    origin = service_url(req.service_url)
    previous = settings()
    # Never carry a credential over to a different service origin.
    key = (
        req.upload_key
        if req.upload_key is not None
        else (previous.get("upload_key", "") if previous.get("service_url") == origin else "")
    )
    write_json_atomic(settings_path(), {"service_url": origin, "upload_key": key})
    settings_path().chmod(0o600)
    return {"service_url": origin, "has_upload_key": bool(key)}


@router.post("/shares", status_code=201)
async def create_share(req: CreateShare, request: Request):
    mgr = request.app.state.thread_manager
    try:
        if await mgr.is_thread_turn_active(req.thread_id):
            raise HTTPException(409, "Wait for the current turn to finish before sharing")
        # No await while copying durable conversation records: turn writers use this event loop.
        snapshot = build_snapshot(
            mgr.store, mgr.store.load_thread(req.thread_id), include_project=req.include_project
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, "Conversation or attachment not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result = await remote(
        "POST",
        "/v1/shares",
        payload={
            "snapshot": snapshot.model_dump(mode="json"),
            "expires_in_days": req.expires_in_days,
        },
        auth=True,
    )
    origin, _ = configured()
    token = result.get("token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(502, "Share service returned an invalid link")
    url = f"{origin}/s/{token}"
    if origin == DEFAULT_SERVICE_URL:
        deletion = result.get("delete_key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", deletion):
            raise HTTPException(502, "Share service returned an invalid deletion credential")
        # One file per share avoids concurrent uploads overwriting each other's credentials.
        path = user_deepseek_dir() / "shares" / f"{token}.json"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json_atomic(path, {"url": url, "delete_key": deletion})
        path.chmod(0o600)
    return {"url": url, "expires_at": result["expires_at"]}


@router.post("/preview")
async def preview(req: ShareLink):
    _, snapshot = await download(req.url)
    return {
        "title": snapshot.title,
        "created_at": snapshot.created_at.isoformat(),
        "turn_count": len(snapshot.turns),
        "source_workspace": snapshot.source_workspace,
        "model": snapshot.model,
        "project_commit": snapshot.project.commit if snapshot.project else None,
        "files": [f.path for f in snapshot.project.files] if snapshot.project else [],
        "messages": [
            {"role": i.kind.value, "text": (i.detail or i.summary)[:2000]}
            for i in snapshot.items
            if i.kind.value in {"user_message", "agent_message"}
        ][-10:],
    }


@router.post("/restore", status_code=201)
async def restore(req: RestoreShare, request: Request):
    token, snapshot = await download(req.url)
    return await request.app.state.thread_manager._complete_mutation(
        _restore_downloaded(req, request, token, snapshot)
    )


async def _restore_downloaded(req, request, token, snapshot):
    scratch = None
    if not (req.workspace or "").strip():
        if req.restore_project and snapshot.project:
            raise HTTPException(400, "Choose the local project to restore its files")
        scratch = user_deepseek_dir() / "workspace" / f"shared-{uuid.uuid4().hex[:10]}"
        scratch.mkdir(parents=True, exist_ok=False)
    workspace = scratch or await asyncio.to_thread(
        lambda: Path(req.workspace).expanduser().resolve()
    )
    if not workspace.is_dir():
        raise HTTPException(400, "Choose an existing local project directory")
    destination = None
    try:
        if req.restore_project and snapshot.project:
            destination = workspace.parent / f"{workspace.name}-shared-{uuid.uuid4().hex[:10]}"
            await asyncio.to_thread(restore_project, snapshot.project, workspace, destination)
        thread = import_snapshot(
            request.app.state.thread_manager.store, snapshot, destination or workspace, token
        )
    except BaseException as exc:
        if scratch:
            scratch.rmdir()
        if destination and destination.exists():
            await asyncio.to_thread(
                git, workspace, "worktree", "remove", "--force", str(destination)
            )
        if isinstance(exc, (ValueError, OSError)):
            raise HTTPException(400, str(exc)) from exc
        raise
    return thread.model_dump(mode="json")


@router.post("/revoke")
async def revoke(req: ShareLink):
    parsed = urlsplit(req.url.strip())
    if f"{parsed.scheme}://{parsed.netloc}" == DEFAULT_SERVICE_URL:
        token = token_from_link(req.url, DEFAULT_SERVICE_URL)
        path = user_deepseek_dir() / "shares" / f"{token}.json"
        owned = read_json_or_none(path) or {}
        if not owned.get("delete_key"):
            raise HTTPException(403, "Revoke this link on the computer that created it")
        # The credential is scoped to the built-in service, never to a pasted external URL.
        await remote("DELETE", f"/v1/shares/{token}", auth=True, delete_key=owned["delete_key"])
        path.unlink(missing_ok=True)
        return {"revoked": True}
    origin, _ = configured()
    token = token_from_link(req.url, origin)
    await remote("DELETE", f"/v1/shares/{token}", auth=True)
    return {"revoked": True}
