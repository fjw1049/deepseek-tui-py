"""Language Server Protocol integration.

Consolidates the former lsp/ package.
"""

from __future__ import annotations

# Key used in ToolContext.metadata for the LspManager instance.
LSP_MANAGER_KEY = "lsp_manager"



# ======================================================================
# From diagnostics.py
# ======================================================================

"""LSP diagnostic models and rendering."""


from dataclasses import dataclass
from enum import IntEnum


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


from enum import Enum
from pathlib import Path


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


import asyncio
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any



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


# ======================================================================
# From manager.py
# ======================================================================

"""LSP manager for lazy server spawning and diagnostics collection."""


import asyncio
from pathlib import Path



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
        self._warned_missing: set[Language] = set()

    async def diagnostics_for(self, path: Path, content: str, seq: int) -> list[DiagnosticBlock]:
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
            if seq == 1:
                await client.did_open(path, content)
            else:
                await client.did_change(path, content, seq)

            await asyncio.sleep(self.config.poll_after_edit_ms / 1000.0)

            diagnostics = client.get_diagnostics(path)
            filtered = self._filter_diagnostics(diagnostics)
            if not filtered:
                return []

            return [DiagnosticBlock(path=str(path), diagnostics=filtered)]
        except Exception:
            return []

    async def _get_or_spawn_client(self, lang: Language) -> LspClient | None:
        """Get or spawn an LSP client for a language."""
        if lang in self._clients:
            return self._clients[lang]

        server_cmd = self.config.servers.get(lang.as_key())
        if server_cmd:
            command = server_cmd[0]
            args = server_cmd[1:]
        else:
            server_info = server_for(lang)
            if server_info is None:
                return None
            command, args = server_info

        try:
            transport = StdioLspTransport(command, args)
            client = LspClient(transport, lang)
            await client.start()
            self._clients[lang] = client
            return client
        except Exception:
            if lang not in self._warned_missing:
                self._warned_missing.add(lang)
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
        for client in self._clients.values():
            await client.close()
        self._clients.clear()


# ======================================================================
# From hooks.py
# ======================================================================

"""Post-edit path extraction helpers.

Mirrors ``crates/tui/src/core/engine/lsp_hooks.rs:16-71`` — the helpers
that inspect a tool-call input and return the files the tool just
edited. The engine feeds each path into :meth:`LspManager.diagnostics_for`
so the next LLM turn sees fresh diagnostics.
"""


from pathlib import Path
from typing import Any

_EDIT_TOOLS = {"edit_file", "write_file"}


def edited_paths_for_tool(tool_name: str, tool_input: Any) -> list[Path]:
    """Return workspace-relative paths the tool just edited.

    Mirrors Rust ``edited_paths_for_tool`` (lsp_hooks.rs:16-49). Returns
    ``[]`` for non-edit tools so callers can treat it as a pure gate.
    """
    if not isinstance(tool_input, dict):
        return []

    if tool_name in _EDIT_TOOLS:
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            return [Path(path)]
        return []

    if tool_name == "apply_patch":
        out: list[Path] = []
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            out.append(Path(path))
        files = tool_input.get("files")
        if isinstance(files, list):
            for entry in files:
                if isinstance(entry, dict):
                    p = entry.get("path")
                    if isinstance(p, str) and p:
                        out.append(Path(p))
        # Rust also handles `changes` (our native shape), same logic.
        changes = tool_input.get("changes")
        if isinstance(changes, list):
            for entry in changes:
                if isinstance(entry, dict):
                    p = entry.get("path")
                    if isinstance(p, str) and p:
                        out.append(Path(p))
        # Fallback: parse `+++ b/...` from the patch text.
        if not out:
            patch = tool_input.get("patch")
            if isinstance(patch, str) and patch:
                out.extend(parse_patch_paths(patch))
        return out

    return []


def parse_patch_paths(patch: str) -> list[Path]:
    """Extract ``+++ b/<path>`` targets from a unified diff.

    Mirrors Rust ``parse_patch_paths`` (lsp_hooks.rs:56-71). Best-effort
    only; the real apply_patch validates the patch shape.
    """
    out: list[Path] = []
    for line in patch.splitlines():
        if not line.startswith("+++ "):
            continue
        rest = line[len("+++ ") :].strip()
        # Strip the `b/` prefix conventional for git diffs.
        if rest.startswith("b/"):
            rest = rest[2:]
        if rest == "/dev/null" or not rest:
            continue
        out.append(Path(rest))
    return out
