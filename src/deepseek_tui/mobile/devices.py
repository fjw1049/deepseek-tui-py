"""Personal-device pairing; only digests of short-lived codes and tokens persist."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request

from deepseek_tui.config.paths import user_deepseek_dir
from deepseek_tui.utils import write_text_atomic
from deepseek_tui.workspace.project_lease import FileLease

router = APIRouter(prefix="/v1/mobile/devices", tags=["mobile-devices"])
PAIR_PATH = "/v1/mobile/devices/pair"
CODE_TTL = 300
MAX_DEVICES = 100


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _path():
    return user_deepseek_dir() / "mobile-devices.json"


def _load() -> dict:
    try:
        data = json.loads(_path().read_text())
    except FileNotFoundError:
        return {"devices": [], "codes": [], "attempts": []}
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "Device registry unavailable") from exc
    if not isinstance(data, dict) or any(
        not isinstance(data.get(k), list) for k in ("devices", "codes", "attempts")
    ):
        raise HTTPException(503, "Device registry unavailable")
    return data


def _save(data: dict):
    path = _path()
    write_text_atomic(path, json.dumps(data))
    os.chmod(path, 0o600)


@contextmanager
def _locked():
    lease = FileLease(user_deepseek_dir() / "locks" / "mobile-devices.lock")
    lease.acquire_blocking()
    try:
        yield _load()
    finally:
        lease.release()


def device_for_token(token: str | None) -> dict | None:
    if not token or not token.startswith("dsd_") or len(token) > 200:
        return None
    digest = _digest(token)
    for device in _load()["devices"]:
        if not device.get("revoked_at") and hmac.compare_digest(
            device.get("token_hash", ""), digest
        ):
            return {key: device[key] for key in ("id", "name", "created_at")}
    return None


def create_code() -> dict:
    with _locked() as data:
        now = time.time()
        data["codes"] = [code for code in data["codes"] if code["expires_at"] > now][-9:]
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(12))
        expires = now + CODE_TTL
        data["codes"].append({"hash": _digest(code), "expires_at": expires})
        _save(data)
        return {"code": code[:6] + "-" + code[6:], "expires_at": expires}


def consume_code(code: str, name: str, address: str) -> dict:
    with _locked() as data:
        now = time.time()
        attempts = [item for item in data["attempts"] if item["at"] > now - 60]
        ip = _digest(address)
        if len(attempts) >= 60 or sum(item["ip"] == ip for item in attempts) >= 10:
            raise HTTPException(429, "Too many pairing attempts; wait one minute")
        attempts.append({"at": now, "ip": ip})
        data["attempts"] = attempts
        data["codes"] = [item for item in data["codes"] if item["expires_at"] > now]
        normalized = code.strip().upper().replace("-", "")
        found = next(
            (
                item
                for item in data["codes"]
                if hmac.compare_digest(item["hash"], _digest(normalized))
            ),
            None,
        )
        if found is None:
            _save(data)
            raise HTTPException(400, "Pairing code is invalid, expired, or already used")
        active = [item for item in data["devices"] if not item.get("revoked_at")]
        if len(active) >= MAX_DEVICES:
            _save(data)
            raise HTTPException(409, "Device limit reached; revoke an unused device first")
        token = "dsd_" + secrets.token_urlsafe(32)
        device = {
            "id": secrets.token_hex(12),
            "name": name.strip(),
            "created_at": now,
            "revoked_at": None,
            "token_hash": _digest(token),
        }
        if len(data["devices"]) >= MAX_DEVICES:
            data["devices"] = active
        data["devices"].append(device)
        data["codes"].remove(found)
        _save(data)
        return {"token": token, "device": {k: v for k, v in device.items() if k != "token_hash"}}


def list_devices() -> list[dict]:
    return [
        {key: value for key, value in item.items() if key != "token_hash"}
        for item in _load()["devices"]
    ]


def revoke_device(device_id: str) -> dict:
    with _locked() as data:
        device = next((item for item in data["devices"] if item["id"] == device_id), None)
        if device is None:
            raise HTTPException(404, "Device not found")
        device["revoked_at"] = device.get("revoked_at") or time.time()
        _save(data)
        return {"revoked": True}


def _admin(request: Request):
    if getattr(request.state, "runtime_role", None) != "admin":
        raise HTTPException(403, "Only the computer administrator can manage paired devices")


@router.post("/pair-codes")
async def pair_code(request: Request):
    _admin(request)
    return await asyncio.to_thread(create_code)


@router.post("/pair")
async def pair(request: Request):
    if not getattr(request.app.state, "runtime_auth_token", None):
        raise HTTPException(503, "Enable Runtime authentication before pairing devices")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 2048:
            raise HTTPException(413, "Pairing request is too large")
        raw.extend(chunk)
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, "Invalid pairing request") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid pairing request")
    code, name = body.get("code"), body.get("name")
    if (
        not isinstance(code, str)
        or len(code) > 32
        or not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 80
    ):
        raise HTTPException(400, "Enter a pairing code and device name (1–80 characters)")
    address = request.client.host if request.client else "unknown"
    return await asyncio.to_thread(consume_code, code, name, address)


@router.get("/session")
async def session(request: Request):
    return {
        "role": getattr(request.state, "runtime_role", "unsecured"),
        "device": getattr(request.state, "runtime_device", None),
    }


@router.get("")
async def devices(request: Request):
    _admin(request)
    return await asyncio.to_thread(list_devices)


@router.delete("/{device_id}")
async def revoke(request: Request, device_id: str):
    _admin(request)
    return await asyncio.to_thread(revoke_device, device_id)
