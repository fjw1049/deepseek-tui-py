"""Language Server Protocol integration.

Consolidates the former lsp/ package.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from enum import Enum
from pathlib import Path
import asyncio
import json
import logging
import os
from urllib.parse import urlsplit
from urllib.request import url2pathname
from abc import ABC, abstractmethod
from typing import Any

# Key used in ToolContext.metadata for the LspManager instance.
LSP_MANAGER_KEY = "lsp_manager"



# ======================================================================
# From diagnostics.py
# ======================================================================

"""LSP diagnostic models and rendering."""




class Severity(IntEnum):
    """LSP diagnostic severity."""

    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


@dataclass(slots=True)
class Diagnostic:
    """A single LSP diagnostic."""

    severity: Severity
    line: int
    column: int
    message: str
    source: str | None = None


@dataclass(slots=True)
class DiagnosticBlock:
    """Diagnostics for a single file."""

    path: str
    diagnostics: list[Diagnostic]


def render_blocks(blocks: list[DiagnosticBlock]) -> str:
    """Render diagnostic blocks as markdown."""
    if not blocks:
        return ""
    lines: list[str] = []
    for block in blocks:
        lines.append(f"**{block.path}**")
        for diag in block.diagnostics:
            severity_label = {
                Severity.ERROR: "error",
                Severity.WARNING: "warning",
                Severity.INFORMATION: "info",
                Severity.HINT: "hint",
            }.get(diag.severity, "unknown")
            loc = f"{diag.line}:{diag.column}"
            source_tag = f" [{diag.source}]" if diag.source else ""
            lines.append(f"  - {loc} {severity_label}{source_tag}: {diag.message}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ======================================================================
# From registry.py
# ======================================================================

"""Language detection and LSP server registry."""




class Language(Enum):
    """Supported languages for LSP integration."""

    RUST = "rust"
    GO = "go"
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    C = "c"
    CPP = "cpp"
    OTHER = "other"

    def as_key(self) -> str:
        """Stable lowercase key for config overrides."""
        return self.value

    def language_id(self) -> str:
        """LSP languageId for textDocument/didOpen."""
        if self == Language.OTHER:
            return "plaintext"
        return str(self.value)


def detect_language(path: Path) -> Language:
    """Detect language from file extension."""
    ext = path.suffix.lower().lstrip(".")
    if not ext:
        return Language.OTHER
    mapping = {
        "rs": Language.RUST,
        "go": Language.GO,
        "py": Language.PYTHON,
        "pyi": Language.PYTHON,
        "ts": Language.TYPESCRIPT,
        "tsx": Language.TYPESCRIPT,
        "js": Language.JAVASCRIPT,
        "jsx": Language.JAVASCRIPT,
        "mjs": Language.JAVASCRIPT,
        "cjs": Language.JAVASCRIPT,
        "c": Language.C,
        "h": Language.C,
        "cpp": Language.CPP,
        "cc": Language.CPP,
        "cxx": Language.CPP,
        "hpp": Language.CPP,
        "hxx": Language.CPP,
        "hh": Language.CPP,
    }
    return mapping.get(ext, Language.OTHER)


def server_for(lang: Language) -> tuple[str, list[str]] | None:
    """Return (command, args) for the LSP server of this language."""
    registry = {
        Language.RUST: ("rust-analyzer", []),
        Language.GO: ("gopls", ["serve"]),
        Language.PYTHON: ("pyright-langserver", ["--stdio"]),
        Language.TYPESCRIPT: ("typescript-language-server", ["--stdio"]),
        Language.JAVASCRIPT: ("typescript-language-server", ["--stdio"]),
        Language.C: ("clangd", []),
        Language.CPP: ("clangd", []),
    }
    return registry.get(lang)


# ======================================================================
# From client.py
# ======================================================================

"""LSP client and transport layer."""





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
                if not 0 < content_length <= 16 * 1024 * 1024:
                    raise ValueError("LSP Content-Length out of bounds")
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


def _document_key(path: Path) -> str:
    return Path(os.path.abspath(path)).as_posix()


def _path_from_uri(uri: str) -> str | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "file" or parsed.query or parsed.fragment:
        return None
    path = url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc != "localhost":
        if os.name != "nt":
            return None
        path = f"//{parsed.netloc}{path}"
    return _document_key(Path(path))


class LspClient:
    """LSP client for a single language server."""

    def __init__(self, transport: LspTransport, language: Language, *, request_timeout: float = 10.0) -> None:
        self.transport = transport
        self.language = language
        self.request_timeout = request_timeout
        self._closed = False
        self._document_locks: dict[str, asyncio.Lock] = {}
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._diagnostics: dict[str, list[Diagnostic]] = {}
        self._receive_task: asyncio.Task[None] | None = None
        # Per-document version, and the fact that we opened it at all. A
        # server drops didChange for a document it never saw open, and
        # requires versions to increase, so neither can be derived from a
        # counter that belongs to the conversation rather than the file.
        self._versions: dict[str, int] = {}
        # Set when the server publishes for a URI, so a caller can wait for
        # the answer instead of sleeping for however long it might take.
        self._published: dict[str, asyncio.Event] = {}

    @property
    def is_running(self) -> bool:
        return not self._closed and self._receive_task is not None and not self._receive_task.done()

    async def start(self) -> None:
        async def initialize() -> None:
            await self.transport.start()
            self._receive_task = asyncio.create_task(self._receive_loop())
            await self._initialize()

        try:
            await asyncio.wait_for(initialize(), self.request_timeout)
        except BaseException:
            await self.close()
            raise

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
        async def exchange() -> Any:
            await self.transport.send({
                "jsonrpc": "2.0", "id": msg_id, "method": method, "params": params,
            })
            return await future

        try:
            return await asyncio.wait_for(exchange(), self.request_timeout)
        finally:
            self._pending.pop(msg_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def _notify(self, method: str, params: Any) -> None:
        await asyncio.wait_for(self.transport.send({
            "jsonrpc": "2.0", "method": method, "params": params,
        }), self.request_timeout)

    async def _receive_loop(self) -> None:
        """Receive loop for handling server messages."""
        try:
            while True:
                msg = await self.transport.receive()
                if msg is None:
                    break
                if "id" in msg and msg["id"] in self._pending:
                    future = self._pending.pop(msg["id"])
                    if future.done():
                        continue
                    if "result" in msg:
                        future.set_result(msg["result"])
                    elif "error" in msg:
                        future.set_exception(RuntimeError(msg["error"].get("message", "LSP error")))
                elif msg.get("method") == "textDocument/publishDiagnostics":
                    self._handle_diagnostics(msg["params"])
        except Exception:  # noqa: BLE001 — fail the connection and all its waiters.
            logging.getLogger(__name__).warning("LSP receive failed", exc_info=True)
        finally:
            self._closed = True
            for event in self._published.values():
                event.set()
            # Server died or stream hit EOF: fail every in-flight request so
            # _request() callers don't await a future that can never resolve.
            pending, self._pending = self._pending, {}
            for future in pending.values():
                if not future.done():
                    future.set_exception(
                        RuntimeError("LSP server connection closed")
                    )

    def _handle_diagnostics(self, params: dict[str, Any]) -> None:
        """Handle publishDiagnostics notification."""
        uri = params.get("uri", "")
        if not isinstance(uri, str):
            return
        path = _path_from_uri(uri)
        if path is None:
            return
        version = params.get("version")
        expected = self._versions.get(path)
        if version is not None and expected is not None and version != expected:
            return
        diagnostics = []
        for diag in params.get("diagnostics", []):
            severity = Severity(diag.get("severity", 1))
            line = diag.get("range", {}).get("start", {}).get("line", 0) + 1
            column = diag.get("range", {}).get("start", {}).get("character", 0) + 1
            message = diag.get("message", "")
            source = diag.get("source")
            diagnostics.append(Diagnostic(severity, line, column, message, source))
        self._diagnostics[path] = diagnostics
        self._publication_event(path).set()

    def _publication_event(self, path: str) -> asyncio.Event:
        event = self._published.get(path)
        if event is None:
            event = asyncio.Event()
            self._published[path] = event
        return event

    async def sync_and_await_diagnostics(
        self, path: Path, content: str, timeout_s: float
    ) -> list[Diagnostic]:
        """Push the new content and wait for the server's verdict on it.

        Returns as soon as the server publishes, which for a clean file is
        an empty list rather than silence — so the timeout is a bound on
        pathological cases, not the price of every edit.
        """
        key = _document_key(path)
        lock = self._document_locks.setdefault(key, asyncio.Lock())

        async def sync() -> list[Diagnostic]:
            async with lock:
                event = self._publication_event(key)
                event.clear()
                previous = self._versions.get(key, 0)
                self._versions[key] = previous + 1
                try:
                    if previous:
                        await self.did_change(path, content, previous + 1)
                    else:
                        await self.did_open(path, content)
                except BaseException:
                    # A partial send has unknown document state. Reconnect
                    # rather than issuing a later didChange to an unopened file.
                    await self.close()
                    raise
                await event.wait()
                return self.get_diagnostics(path) if not self._closed else []

        try:
            return await asyncio.wait_for(sync(), timeout_s)
        except asyncio.TimeoutError:
            return []

    async def did_open(self, path: Path, content: str) -> None:
        """Send didOpen notification."""
        await self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": Path(_document_key(path)).as_uri(),
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
                    "uri": Path(_document_key(path)).as_uri(),
                    "version": version,
                },
                "contentChanges": [{"text": content}],
            },
        )

    def get_diagnostics(self, path: Path) -> list[Diagnostic]:
        """Get diagnostics for a file."""
        return self._diagnostics.get(_document_key(path), [])

    async def close(self) -> None:
        """Close the client."""
        self._closed = True
        task, self._receive_task = self._receive_task, None
        try:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        finally:
            await self.transport.close()


# ======================================================================
# From manager.py
# ======================================================================

"""LSP manager for lazy server spawning and diagnostics collection."""





class LspConfig:
    """LSP configuration."""

    def __init__(
        self,
        enabled: bool = True,
        poll_after_edit_ms: int = 5000,
        max_diagnostics_per_file: int = 20,
        include_warnings: bool = False,
        servers: dict[str, list[str]] | None = None,
    ) -> None:
        self.enabled = enabled
        self.poll_after_edit_ms = poll_after_edit_ms
        self.max_diagnostics_per_file = max_diagnostics_per_file
        self.include_warnings = include_warnings
        self.servers = servers or {}


class LspManager:
    """Manages LSP clients and diagnostics collection."""

    def __init__(self, config: LspConfig) -> None:
        self.config = config
        self._clients: dict[Language, LspClient] = {}
        self._unavailable: set[Language] = set()
        self._starting: dict[Language, asyncio.Task[LspClient | None]] = {}
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    async def diagnostics_for(self, path: Path, content: str) -> list[DiagnosticBlock]:
        """Get diagnostics for a file after an edit."""
        if not self.config.enabled:
            return []

        lang = detect_language(path)
        if lang == Language.OTHER:
            return []

        client = await self._get_or_spawn_client(lang)
        if client is None:
            return []

        try:
            diagnostics = await client.sync_and_await_diagnostics(
                path, content, self.config.poll_after_edit_ms / 1000.0
            )
            filtered = self._filter_diagnostics(diagnostics)
            if not filtered:
                return []

            return [DiagnosticBlock(path=str(path), diagnostics=filtered)]
        except Exception:
            return []

    async def _get_or_spawn_client(self, lang: Language) -> LspClient | None:
        """Get or spawn an LSP client for a language."""
        if self._closed or lang in self._unavailable:
            return None
        client = self._clients.get(lang)
        if client is not None and client.is_running:
            return client
        task = self._starting.get(lang)
        if task is None or task.done():
            task = asyncio.create_task(self._spawn_client(lang), name=f"lsp-start-{lang.value}")
            self._starting[lang] = task
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(task)

    async def _spawn_client(self, lang: Language) -> LspClient | None:
        previous = self._clients.pop(lang, None)
        if previous is not None:
            await previous.close()
        server_cmd = self.config.servers.get(lang.as_key())
        if server_cmd:
            command = server_cmd[0]
            args = server_cmd[1:]
        else:
            server_info = server_for(lang)
            if server_info is None:
                self._unavailable.add(lang)
                return None
            command, args = server_info

        try:
            transport = StdioLspTransport(command, args)
            client = LspClient(transport, lang)
            await client.start()
            if self._closed:
                await client.close()
                return None
            self._clients[lang] = client
            return client
        except asyncio.CancelledError:
            await client.close()
            raise
        except Exception:
            await client.close()
            self._unavailable.add(lang)
            logging.getLogger(__name__).warning(
                "lsp_server_unavailable language=%s command=%s — diagnostics "
                "disabled for this language; install it or set "
                "[lsp.servers] in config",
                lang.as_key(),
                command,
            )
            return None

    def _filter_diagnostics(self, diagnostics: list[Diagnostic]) -> list[Diagnostic]:
        """Filter and limit diagnostics."""
        filtered = []
        for diag in diagnostics:
            if diag.severity == Severity.ERROR:
                filtered.append(diag)
            elif diag.severity == Severity.WARNING and self.config.include_warnings:
                filtered.append(diag)

        filtered.sort(key=lambda d: (d.severity, d.line, d.column))
        return filtered[: self.config.max_diagnostics_per_file]

    async def close_all(self) -> None:
        """Close all LSP clients."""
        self._closed = True
        if self._close_task is None:
            async def drain() -> None:
                tasks = list(self._starting.values())
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self._starting.clear()
                clients = list(self._clients.values())
                self._clients.clear()
                await asyncio.gather(*(c.close() for c in clients), return_exceptions=True)

            self._close_task = asyncio.create_task(drain(), name="lsp-close")
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await self._close_task
            raise


# ======================================================================
# From hooks.py
# ======================================================================

"""Post-edit path extraction helpers.

The helpers inspect a tool-call input and return the files the tool just
edited. The engine feeds each path into :meth:`LspManager.diagnostics_for`
so the next LLM turn sees fresh diagnostics.
"""



_EDIT_TOOLS = {"edit_file", "write_file"}


def edited_paths_for_tool(tool_name: str, tool_input: Any) -> list[Path]:
    """Return workspace-relative paths the tool just edited.

    Returns ``[]`` for non-edit tools so callers can treat it as a pure gate.
    """
    if not isinstance(tool_input, dict):
        return []

    if tool_name in _EDIT_TOOLS:
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            return [Path(path)]
        return []

    return []
