"""LSP client and transport layer."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from deepseek_tui.lsp.diagnostics import Diagnostic, Severity
from deepseek_tui.lsp.registry import Language


class LspTransport(ABC):
    """Abstract LSP transport."""

    @abstractmethod
    async def start(self) -> None:
        """Start the transport."""

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON-RPC message."""

    @abstractmethod
    async def receive(self) -> dict[str, Any] | None:
        """Receive a JSON-RPC message (None on EOF)."""

    @abstractmethod
    async def close(self) -> None:
        """Close the transport."""


class StdioLspTransport(LspTransport):
    """Stdio-based LSP transport."""

    def __init__(self, command: str, args: list[str]) -> None:
        self.command = command
        self.args = args
        self._process: asyncio.subprocess.Process | None = None
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def send(self, message: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Transport not started")
        async with self._write_lock:
            payload = json.dumps(message).encode("utf-8")
            header = f"Content-Length: {len(payload)}\r\n\r\n".encode()
            self._process.stdin.write(header + payload)
            await self._process.stdin.drain()

    async def receive(self) -> dict[str, Any] | None:
        if not self._process or not self._process.stdout:
            return None
        async with self._read_lock:
            try:
                headers = {}
                while True:
                    line = await self._process.stdout.readline()
                    if not line:
                        return None
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        break
                    if ":" in line_str:
                        key, _, value = line_str.partition(":")
                        headers[key.strip().lower()] = value.strip()
                content_length = int(headers.get("content-length", "0"))
                if content_length == 0:
                    return None
                payload = await self._process.stdout.readexactly(content_length)
                result: dict[str, Any] = json.loads(payload.decode("utf-8"))
                return result
            except (asyncio.IncompleteReadError, json.JSONDecodeError):
                return None

    async def close(self) -> None:
        if self._process:
            if self._process.stdin:
                self._process.stdin.close()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()


class LspClient:
    """LSP client for a single language server."""

    def __init__(self, transport: LspTransport, language: Language) -> None:
        self.transport = transport
        self.language = language
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._diagnostics: dict[str, list[Diagnostic]] = {}
        self._receive_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the client and initialize the server."""
        await self.transport.start()
        self._receive_task = asyncio.create_task(self._receive_loop())
        await self._initialize()

    async def _initialize(self) -> None:
        """Send initialize request."""
        await self._request(
            "initialize",
            {
                "processId": None,
                "rootUri": None,
                "capabilities": {},
            },
        )
        await self._notify("initialized", {})

    async def _request(self, method: str, params: Any) -> Any:
        """Send a request and wait for response."""
        msg_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.Future()
        self._pending[msg_id] = future
        await self.transport.send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": method,
                "params": params,
            }
        )
        return await future

    async def _notify(self, method: str, params: Any) -> None:
        """Send a notification (no response expected)."""
        await self.transport.send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    async def _receive_loop(self) -> None:
        """Receive loop for handling server messages."""
        while True:
            msg = await self.transport.receive()
            if msg is None:
                break
            if "id" in msg and msg["id"] in self._pending:
                future = self._pending.pop(msg["id"])
                if "result" in msg:
                    future.set_result(msg["result"])
                elif "error" in msg:
                    future.set_exception(RuntimeError(msg["error"].get("message", "LSP error")))
            elif msg.get("method") == "textDocument/publishDiagnostics":
                self._handle_diagnostics(msg["params"])

    def _handle_diagnostics(self, params: dict[str, Any]) -> None:
        """Handle publishDiagnostics notification."""
        uri = params.get("uri", "")
        if uri.startswith("file://"):
            path = uri[7:]
        else:
            path = uri
        diagnostics = []
        for diag in params.get("diagnostics", []):
            severity = Severity(diag.get("severity", 1))
            line = diag.get("range", {}).get("start", {}).get("line", 0) + 1
            column = diag.get("range", {}).get("start", {}).get("character", 0) + 1
            message = diag.get("message", "")
            source = diag.get("source")
            diagnostics.append(Diagnostic(severity, line, column, message, source))
        self._diagnostics[path] = diagnostics

    async def did_open(self, path: Path, content: str) -> None:
        """Send didOpen notification."""
        await self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": f"file://{path.as_posix()}",
                    "languageId": self.language.language_id(),
                    "version": 1,
                    "text": content,
                }
            },
        )

    async def did_change(self, path: Path, content: str, version: int) -> None:
        """Send didChange notification."""
        await self._notify(
            "textDocument/didChange",
            {
                "textDocument": {
                    "uri": f"file://{path.as_posix()}",
                    "version": version,
                },
                "contentChanges": [{"text": content}],
            },
        )

    def get_diagnostics(self, path: Path) -> list[Diagnostic]:
        """Get diagnostics for a file."""
        return self._diagnostics.get(path.as_posix(), [])

    async def close(self) -> None:
        """Close the client."""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        await self.transport.close()
