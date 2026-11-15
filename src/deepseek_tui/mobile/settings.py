"""Authenticated, bounded adapters to existing skills, project memory and MCP stores.

Mount on the Runtime app (RuntimeAuthMiddleware applies). Saving MCP does not
reload connectors or execute commands; a Runtime restart is explicitly required.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request

from deepseek_tui.integrations import skills
from deepseek_tui.state.memory import MemoryStore
from deepseek_tui.utils import write_json_atomic
from deepseek_tui.workspace.execution import project_root
from deepseek_tui.workspace.project_lease import FileLease

router = APIRouter(prefix="/v1/mobile-settings", tags=["mobile-settings"])
MAX_BODY = 64 * 1024
MAX_DOC = 256 * 1024


async def body(request: Request) -> dict:
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > MAX_BODY:
            raise HTTPException(413, "Settings request exceeds 64 KiB")
    try:
        value = json.loads(chunks)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "JSON object required")
    return value


def name(value: str) -> str:
    if not re.fullmatch(r"[\w.-]{1,120}", value) or value in {".", ".."}:
        raise HTTPException(400, "Invalid item name")
    return value


def read_small(path: Path, cap: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Only regular files are supported")
        value = stream.read(cap + 1)
    if len(value) > cap:
        raise ValueError("File exceeds supported size")
    return value


def skill_root() -> Path:
    root = skills.default_skills_dir()
    if root.is_symlink():
        raise HTTPException(403, "Skills directory cannot be a symbolic link")
    return root


def skill_path(identifier: str) -> Path:
    root = skill_root()
    path = root / name(identifier)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(403, "Skill path is outside the user skills directory")
    return path


def skill_record(identifier: str, *, content: bool = False) -> dict:
    directory = skill_path(identifier)
    try:
        doc = read_small(directory / "SKILL.md", MAX_DOC).decode("utf-8")
        parsed = skills._parse_skill_file(directory / "SKILL.md", content=doc)
    except FileNotFoundError as exc:
        raise HTTPException(404, "User skill not found") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(400, "Cannot read this skill document") from exc
    builtin = (directory / skills.SYSTEM_VERSION_MARKER).exists()
    out = {
        "id": identifier,
        "name": parsed.name,
        "description": parsed.description,
        "builtin": builtin,
        "can_delete": not builtin and (directory / skills.INSTALLED_FROM_MARKER).is_file(),
    }
    if content:
        out["content"] = doc
    return out


@router.get("/skills")
async def list_user_skills():
    root = skill_root()

    def inspect():
        records = []
        if root.exists():
            for entry in sorted(islice(root.iterdir(), 500)):
                if entry.is_dir() and not entry.is_symlink() and (entry / "SKILL.md").exists():
                    try:
                        records.append(skill_record(entry.name))
                    except HTTPException:
                        continue
        return {"skills": records}

    return await asyncio.to_thread(inspect)


@router.get("/skills/{identifier}")
async def get_skill(identifier: str):
    return await asyncio.to_thread(skill_record, identifier, content=True)


@router.post("/skills/install", status_code=201)
async def install_skill(request: Request):
    value = await body(request)
    if value.get("confirm") is not True:
        raise HTTPException(400, "Confirm skill installation explicitly")
    source = skills.InstallSource.parse(str(value.get("source", "")))
    if source.kind not in {"local", "github"}:
        raise HTTPException(400, "Use a local directory or github:owner/repo")
    identifier = name(
        str(
            value.get("name")
            or (Path(source.local_path).name if source.kind == "local" else source.repo)
        )
    )

    def install():
        root = skill_root()
        if source.kind == "local":
            total = count = 0
            local = Path(source.local_path)
            if local.is_symlink():
                raise HTTPException(400, "Local skill source cannot be a symbolic link")
            for entry in local.rglob("*"):
                if entry.is_symlink():
                    raise HTTPException(400, "Local skill cannot include symbolic links")
                if entry.is_file():
                    count += 1
                    total += entry.stat().st_size
                    if count > 1000 or total > skills.DEFAULT_MAX_SIZE_BYTES:
                        raise HTTPException(413, "Local skill exceeds installation limit")
        # Reuse the original lock to cover marker removal as part of installation.
        with skills._SKILL_MUTATION_LOCK:
            outcome, message = skills.install(source, root, identifier)
            if outcome == skills.InstallOutcome.FAILED:
                raise HTTPException(400, message)
            if outcome == skills.InstallOutcome.INSTALLED:
                (skill_path(identifier) / skills.TRUSTED_MARKER).unlink(missing_ok=True)
            return {"outcome": outcome.value, "message": message}

    return await asyncio.to_thread(install)


@router.delete("/skills/{identifier}")
async def delete_skill(identifier: str, request: Request):
    if (await body(request)).get("confirm") is not True:
        raise HTTPException(400, "Confirm skill deletion explicitly")

    def remove():
        with skills._SKILL_MUTATION_LOCK:
            if not skill_record(identifier)["can_delete"]:
                raise HTTPException(403, "Built-in or manually installed skills cannot be deleted")
            message = skills.uninstall(identifier, skill_root())
            if not message.startswith("Uninstalled "):
                raise HTTPException(400, message)
            return {"message": message}

    return await asyncio.to_thread(remove)


def memory_store(request: Request, thread_id: str) -> MemoryStore:
    try:
        thread = request.app.state.thread_manager.store.load_thread(thread_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Conversation not found") from exc
    return MemoryStore(project_root(thread))


@router.get("/threads/{thread_id}/memories")
async def list_memories(request: Request, thread_id: str, query: str = "", offset: int = 0):
    if len(query) > 2000 or not 0 <= offset <= 100000:
        raise HTTPException(400, "Invalid memory query")

    def read():
        store = memory_store(request, thread_id)
        entries = store.read(query=query, status="all", offset=offset, limit=20)
        return {
            "entries": [
                {**entry.model_dump(mode="json"), "stale_reason": store.stale_reason(entry)}
                for entry in entries
            ],
            "offset": offset,
        }

    return await asyncio.to_thread(read)


@router.post("/threads/{thread_id}/memories")
@router.patch("/threads/{thread_id}/memories/{entry_id}")
@router.delete("/threads/{thread_id}/memories/{entry_id}")
async def write_memory(request: Request, thread_id: str, entry_id: str = ""):
    value = await body(request)
    action = "forget" if request.method == "DELETE" else "update" if entry_id else "remember"
    if entry_id and type(value.get("revision")) is not int:
        raise HTTPException(400, "Current memory revision is required")
    if action == "forget" and value.get("confirm") is not True:
        raise HTTPException(400, "Confirm memory deletion explicitly")

    def write():
        store = memory_store(request, thread_id)
        fields = {}
        if action == "update":
            existing = store.read(entry_id=entry_id, status="all")
            if not existing:
                raise HTTPException(404, "Memory not found")
            old = existing[0]
            fields = {
                "content": old.content,
                "kind": old.kind,
                "applicability": old.applicability,
                "topic": old.topic,
                "branch": old.branch,
                "expires_at": old.expires_at,
            }
        for key, limit in (("content", 2000), ("kind", 30), ("applicability", 500), ("topic", 100)):
            if key in value:
                if not isinstance(value[key], str) or len(value[key]) > limit:
                    raise HTTPException(400, f"Invalid memory {key}")
                fields[key] = value[key]
        try:
            entry = store.write(
                action=action,
                entry_id=entry_id,
                revision=value.get("revision"),
                source={"type": "user", "thread_id": thread_id, "client": "mobile"},
                **fields,
            )
        except ValueError as exc:
            raise HTTPException(409 if "revision" in str(exc) else 400, str(exc)) from exc
        return entry.model_dump(mode="json")

    return await asyncio.to_thread(write)


def mcp_path(request: Request) -> Path:
    from deepseek_tui.config.paths import user_mcp_config_path

    path = user_mcp_config_path()
    configured = Path(request.app.state.runtime.config.mcp_config_path)
    if configured.resolve() != path.resolve():
        raise HTTPException(409, "Custom MCP config must be managed on the computer")
    if path.is_symlink() or path.parent.is_symlink():
        raise HTTPException(403, "MCP settings cannot be a symbolic link")
    return path


def mcp_read(path: Path) -> tuple[dict, str]:
    try:
        raw = read_small(path, 1024 * 1024)
    except FileNotFoundError:
        raw = b"{}"
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise HTTPException(400, "MCP config must be an object")
    return document, hashlib.sha256(raw).hexdigest()


def public_mcp(document: dict, revision: str) -> dict:
    from deepseek_tui.mcp.config import servers_from_document

    servers = servers_from_document(document)
    return {
        "revision": revision,
        "servers": [
            {
                "name": s.name,
                "enabled": s.enabled,
                "transport": s.transport or ("stdio" if s.command else "streamablehttp"),
                "url_origin": f"{urlsplit(s.url).scheme}://{urlsplit(s.url).hostname}"
                if s.url
                else None,
                "has_command": bool(s.command),
                "args_count": len(s.args),
                "has_env": bool(s.env),
                "has_headers": bool(s.headers),
                "load_policy": s.load_policy,
            }
            for s in servers
        ],
    }


@router.get("/mcp")
async def get_mcp(request: Request):
    def get():
        try:
            document, revision = mcp_read(mcp_path(request))
            return public_mcp(document, revision)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, "Cannot read MCP configuration") from exc

    return await asyncio.to_thread(get)


@router.patch("/mcp/{identifier}")
async def save_mcp(identifier: str, request: Request):
    name(identifier)
    value = await body(request)
    if value.get("confirm") is not True:
        raise HTTPException(400, "Confirm MCP configuration change explicitly")
    allowed = {
        "url",
        "command",
        "args",
        "env",
        "headers",
        "enabled",
        "load_policy",
        "transport",
        "revision",
        "confirm",
    }
    if set(value) - allowed:
        raise HTTPException(400, "Unsupported MCP setting")
    updates = {key: val for key, val in value.items() if key not in {"revision", "confirm"}}
    if "enabled" in updates and type(updates["enabled"]) is not bool:
        raise HTTPException(400, "enabled must be a boolean")
    if "transport" in updates and updates["transport"] not in {"stdio", "sse", "streamablehttp"}:
        raise HTTPException(400, "Invalid transport")
    if "load_policy" in updates and updates["load_policy"] not in {"progressive", "on_focus"}:
        raise HTTPException(400, "Invalid load policy")
    for key in ("url", "command"):
        if key in updates and (
            not isinstance(updates[key], str)
            or len(updates[key]) > 4096
            or not updates[key].strip()
        ):
            raise HTTPException(400, f"Invalid {key}")
    if "url" in updates:
        parsed = urlsplit(updates["url"])
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise HTTPException(400, "Use an HTTP(S) URL without embedded credentials")
    if "args" in updates and (
        not isinstance(updates["args"], list)
        or len(updates["args"]) > 100
        or any(not isinstance(arg, str) or len(arg) > 4096 for arg in updates["args"])
    ):
        raise HTTPException(400, "Invalid command arguments")
    for key in ("env", "headers"):
        if key in updates and (
            not isinstance(updates[key], dict)
            or len(updates[key]) > 30
            or any(
                not isinstance(k, str)
                or not isinstance(v, str)
                or len(k) > 200
                or len(v) > 4096
                or "\n" in k
                or "\r" in k
                or "\0" in k
                or "\0" in v
                or (key == "headers" and ("\r" in v or "\n" in v))
                for k, v in updates[key].items()
            )
        ):
            raise HTTPException(400, f"Invalid {key}")

    def save():
        from deepseek_tui.mcp.config import find_servers_table, servers_from_document

        path = mcp_path(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_name(path.name + ".mobile.lock")
        if lock.is_symlink():
            raise HTTPException(403, "MCP lock cannot be a symbolic link")
        lease = FileLease(lock)
        lease.acquire_blocking()
        try:
            document, revision = mcp_read(path)
            if value.get("revision") != revision:
                raise HTTPException(409, "MCP settings changed; reload before saving")
            container, key, table = find_servers_table(document)
            if table is None:
                raise HTTPException(400, "Unsupported MCP document structure")
            if not document:
                document["mcpServers"] = {}
                table = document["mcpServers"]
            elif key is None and container is document:
                table = document
            record = dict(table.get(identifier, {}))
            for key, val in updates.items():
                if key in {"env", "headers"}:
                    record[key] = {**record.get(key, {}), **val}
                else:
                    record[key] = val
            if updates.get("transport") == "stdio":
                record.pop("url", None)
                record.pop("type", None)
            elif updates.get("transport") in {"sse", "streamablehttp"}:
                record.pop("command", None)
                record.pop("type", None)
            if not (record.get("command") or record.get("url")):
                raise HTTPException(400, "A command or URL is required")
            table[identifier] = record
            servers_from_document(document)
            write_json_atomic(path, document)
            path.chmod(0o600)
            _, revision = mcp_read(path)
            return {**public_mcp(document, revision), "restart_required": True}
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(400, "Cannot save MCP configuration") from exc
        finally:
            lease.release()

    return await asyncio.to_thread(save)
