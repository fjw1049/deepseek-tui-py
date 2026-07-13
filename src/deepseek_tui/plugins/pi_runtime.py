"""Pi Node sidecar runtime — JSON-RPC/stdio tracer bullet.

Spawns ``pi_bridge/bridge.cjs`` which loads package entrypoints through a
minimal ExtensionAPI shim. Full Pi widgets/keybindings/renderers remain
unsupported and must stay reported as degraded by the adapter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

BRIDGE_PATH = Path(__file__).resolve().parent / "pi_bridge" / "bridge.cjs"

_STRIP_TYPES_CACHE: bool | None = None


def node_supports_strip_types(node_bin: str | None = None) -> bool:
    """Return True when Node accepts ``--experimental-strip-types`` (22.6+)."""
    import subprocess

    global _STRIP_TYPES_CACHE
    if _STRIP_TYPES_CACHE is not None and node_bin is None:
        return _STRIP_TYPES_CACHE
    binary = node_bin or shutil.which("node") or "node"
    try:
        completed = subprocess.run(
            [binary, "--experimental-strip-types", "-e", "process.exit(0)"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        ok = completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if node_bin is None:
        _STRIP_TYPES_CACHE = ok
    return ok


def _needs_strip_types(entrypoints: tuple[str, ...], package_root: str) -> bool:
    root = Path(package_root)
    for entry in entrypoints:
        normalized = entry[2:] if entry.startswith("./") else entry
        path = root / normalized
        if normalized.rstrip("/").endswith((".ts", ".tsx")):
            return True
        if path.is_dir():
            if (path / "index.ts").is_file() or (path / "index.tsx").is_file():
                return True
            if not any(
                (path / name).is_file()
                for name in ("index.js", "index.mjs", "index.cjs")
            ):
                if any(path.glob("*.ts")) or any(path.glob("*.tsx")):
                    return True
        elif path.suffix in {".ts", ".tsx"}:
            return True
    return False


class PiRuntimeUnavailable(RuntimeError):
    """Raised when the Pi sidecar cannot start or serve a request."""


@dataclass(frozen=True, slots=True)
class PiProviderSpec:
    plugin_id: str
    package_root: str
    entrypoints: tuple[str, ...]
    peer_dependencies: dict[str, Any] = field(default_factory=dict)
    cwd: str | None = None


@dataclass(frozen=True, slots=True)
class PiToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]
    label: str = ""


class PiNodeRuntime:
    """Session-scoped Node sidecar speaking NDJSON JSON-RPC."""

    def __init__(self, spec: PiProviderSpec, *, node_bin: str | None = None) -> None:
        self.spec = spec
        self.node_bin = node_bin or shutil.which("node") or "node"
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        if self.running:
            return
        if not BRIDGE_PATH.is_file():
            raise PiRuntimeUnavailable(f"Pi bridge missing: {BRIDGE_PATH}")
        if shutil.which(self.node_bin) is None and self.node_bin == "node":
            raise PiRuntimeUnavailable("Node.js executable not found on PATH")
        env = {**os.environ, "DEEPSEEK_PI_BRIDGE": "1"}
        args = [self.node_bin]
        if _needs_strip_types(self.spec.entrypoints, self.spec.package_root):
            if not node_supports_strip_types(self.node_bin):
                raise PiRuntimeUnavailable(
                    "TypeScript Pi entrypoints require Node.js with "
                    "--experimental-strip-types (22.6+)"
                )
            args.append("--experimental-strip-types")
        args.append(str(BRIDGE_PATH))
        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.spec.cwd or self.spec.package_root,
            env=env,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        self._reader_task = asyncio.create_task(self._read_loop())
        await self.request(
            "initialize",
            {
                "packageRoot": self.spec.package_root,
                "entrypoints": list(self.spec.entrypoints),
                "cwd": self.spec.cwd or self.spec.package_root,
            },
        )

    async def list_tools(self) -> list[PiToolInfo]:
        result = await self.request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        out: list[PiToolInfo] = []
        if not isinstance(tools, list):
            return out
        for item in tools:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            schema = item.get("inputSchema") or item.get("parameters") or {}
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            out.append(
                PiToolInfo(
                    name=str(item["name"]),
                    description=str(item.get("description") or ""),
                    input_schema=schema,
                    label=str(item.get("label") or ""),
                )
            )
        return out

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        call_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
                "callId": call_id or name,
            },
        )

    async def list_commands(self) -> list[dict[str, str]]:
        result = await self.request("commands/list", {})
        commands = result.get("commands") if isinstance(result, dict) else None
        if not isinstance(commands, list):
            return []
        return [
            {
                "name": str(item.get("name") or ""),
                "description": str(item.get("description") or ""),
            }
            for item in commands
            if isinstance(item, dict) and item.get("name")
        ]

    async def call_command(self, name: str, args: str = "") -> dict[str, Any]:
        return await self.request("commands/call", {"name": name, "args": args})

    async def session_start(self) -> None:
        await self.request("lifecycle/session_start", {})

    async def session_shutdown(self) -> None:
        await self.request("lifecycle/session_shutdown", {})

    async def shutdown(self) -> None:
        if not self.running:
            return
        try:
            await asyncio.wait_for(self.request("shutdown", {}), timeout=2.0)
        except Exception:  # noqa: BLE001
            _LOG.debug("pi shutdown rpc failed", exc_info=True)
        process = self._process
        self._process = None
        if process is not None:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
        self._reader_task = None
        self._stderr_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(PiRuntimeUnavailable("Pi sidecar stopped"))
        self._pending.clear()

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None:
            raise PiRuntimeUnavailable("Pi sidecar is not running")
        async with self._lock:
            req_id = self._next_id
            self._next_id += 1
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[dict[str, Any]] = loop.create_future()
            self._pending[req_id] = fut
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            self._process.stdin.write(raw)
            await self._process.stdin.drain()
        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise PiRuntimeUnavailable(f"Pi RPC timed out: {method}") from exc

    async def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                _LOG.warning("pi bridge sent invalid JSON: %r", line[:200])
                continue
            if not isinstance(message, dict):
                continue
            req_id = message.get("id")
            if not isinstance(req_id, int):
                continue
            fut = self._pending.pop(req_id, None)
            if fut is None or fut.done():
                continue
            if "error" in message:
                err = message.get("error") or {}
                fut.set_exception(
                    PiRuntimeUnavailable(str(err.get("message") or "Pi RPC error"))
                )
            else:
                result = message.get("result")
                fut.set_result(result if isinstance(result, dict) else {})

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            _LOG.debug("pi bridge: %s", line.decode("utf-8", errors="replace").rstrip())
