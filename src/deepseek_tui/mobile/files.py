"""Bounded mobile transfers scoped to a thread's execution workspace.

Mounted under the app's existing bearer authentication. Never accepts an absolute
path or follows a symlink, including during the actual file open (dir_fd).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from deepseek_tui.media import IMAGE_EXTENSIONS, import_image
from deepseek_tui.mobile.document_text import extract_document_text
from deepseek_tui.tools.path_access import is_sensitive
from deepseek_tui.workspace.execution import execution_root

router = APIRouter(prefix="/v1/threads/{thread_id}", tags=["mobile-files"])
MAX_BYTES = 8 * 1024 * 1024
MAX_BODY = ((MAX_BYTES + 2) // 3) * 4 + 4096
UPLOADS = "mobile-attachments"
_PRIVATE_DIRS = {".git", ".ssh", ".aws", ".deepseek", ".gnupg", ".azure"}


def _owner(thread_id: str) -> str:
    return hashlib.sha256(thread_id.encode()).hexdigest()[:24]


def _root(request: Request, thread_id: str) -> Path:
    manager = getattr(request.app.state, "thread_manager", None)
    if manager is None:
        raise HTTPException(503, "Runtime thread manager is unavailable")
    try:
        thread = manager.store.load_thread(thread_id)
        return execution_root(thread).resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Conversation or workspace not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def _parts(raw: str, thread_id: str) -> list[str]:
    if len(raw) > 2048 or raw.startswith("/") or "\\" in raw or "\x00" in raw:
        raise HTTPException(400, "Use a workspace-relative path")
    parts = raw.split("/") if raw else []
    if any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(400, "Invalid workspace path")
    if any(part in _PRIVATE_DIRS or is_sensitive(Path(part), write=False) for part in parts):
        raise HTTPException(403, "Sensitive files are not available through mobile file browsing")
    if len(parts) > 1 and parts[0] == UPLOADS and parts[1] != _owner(thread_id):
        raise HTTPException(403, "Attachment belongs to another conversation")
    return parts


@contextmanager
def _directory(root: Path, parts: list[str], *, create: bool = False):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _translate(exc: OSError) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(404, "File or directory no longer exists")
    return HTTPException(
        403, "File access denied; symbolic links and special files are unavailable"
    )


def _list(root: Path, parts: list[str], thread_id: str) -> dict:
    entries = []
    truncated = False
    try:
        with _directory(root, parts) as fd:
            # scandir stops after the response limit; no unbounded directory materialization.
            with os.scandir(fd) as iterator:
                for entry in iterator:
                    relative = "/".join([*parts, entry.name])
                    try:
                        _parts(relative, thread_id)
                        info = entry.stat(follow_symlinks=False)
                        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                            continue
                    except (HTTPException, OSError):
                        continue
                    if len(entries) == 300:
                        truncated = True
                        break
                    entries.append(
                        {
                            "name": entry.name,
                            "path": relative,
                            "directory": stat.S_ISDIR(info.st_mode),
                            "size": info.st_size,
                        }
                    )
    except OSError as exc:
        raise _translate(exc) from exc
    entries.sort(key=lambda item: (not item["directory"], item["name"].casefold()))
    return {"path": "/".join(parts), "entries": entries, "truncated": truncated}


def _content(root: Path, parts: list[str]) -> dict:
    if not parts:
        raise HTTPException(400, "Choose a file")
    try:
        with _directory(root, parts[:-1]) as parent:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise HTTPException(403, "Only regular files can be downloaded")
                if info.st_size > MAX_BYTES:
                    raise HTTPException(413, "File exceeds the 8 MiB mobile transfer limit")
                data = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise _translate(exc) from exc
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File exceeds the 8 MiB mobile transfer limit")
    return {
        "name": parts[-1],
        "size": len(data),
        "data_base64": base64.b64encode(data).decode(),
        "path": "/".join(parts),
    }


def _upload(root: Path, thread_id: str, payload: dict) -> dict:
    name, encoded = payload.get("name"), payload.get("data_base64")
    if not isinstance(name, str) or not isinstance(encoded, str) or len(name) > 255:
        raise HTTPException(400, "Provide a filename and base64 file content")
    if not name or "/" in name or "\\" in name or any(ord(c) < 32 for c in name):
        raise HTTPException(400, "Invalid attachment filename")
    _parts(name, thread_id)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "Invalid base64 content") from exc
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Attachment exceeds 8 MiB")
    # Use the original media validator. The original @ mention expansion creates
    # ImageBlocks at send time; this endpoint does not invent a second image protocol.
    image = None
    if Path(name).suffix.lower() in IMAGE_EXTENSIONS:
        try:
            image = import_image(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    safe = re.sub(r"[^\w. -]", "_", name).strip(" .") or "attachment"
    suffix = Path(safe).suffix[:16]
    safe = Path(safe).stem[:100] + suffix
    stored_name = f"{uuid.uuid4().hex}-{safe}"
    parts = [UPLOADS, _owner(thread_id), stored_name]
    try:
        with _directory(root, parts[:-1], create=True) as parent:
            fd = os.open(
                stored_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
            except BaseException:
                os.unlink(stored_name, dir_fd=parent)
                raise
    except OSError as exc:
        raise _translate(exc) from exc
    relative = "/".join(parts)
    return {
        "name": name,
        "path": relative,
        "size": len(data),
        "mention": f'@"{relative}"',
        "kind": "image" if image else "file",
        "image": image.model_dump() if image else None,
        **(
            extract_document_text(data, name)
            if not image and payload.get("extract_text", True) is not False
            else {}
        ),
    }


@router.get("/files")
async def list_files(request: Request, thread_id: str, path: str = "") -> dict:
    return await asyncio.to_thread(
        _list, _root(request, thread_id), _parts(path, thread_id), thread_id
    )


@router.get("/files/content")
async def file_content(request: Request, thread_id: str, path: str) -> dict:
    return await asyncio.to_thread(_content, _root(request, thread_id), _parts(path, thread_id))


@router.post("/attachments")
async def upload_attachment(request: Request, thread_id: str) -> dict:
    root = _root(request, thread_id)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            raise HTTPException(413, "Attachment request exceeds the mobile transfer limit")
        body.extend(chunk)
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(400, "Invalid JSON attachment") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid attachment")
    return await asyncio.to_thread(_upload, root, thread_id, payload)
