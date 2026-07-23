"""MCP transport layer — stdio and SSE/HTTP.

Each transport exposes ``send(dict)`` and ``recv() -> dict``. The MCP
client is oblivious to which one is under the hood — it just pushes
JSON-RPC 2.0 objects through.

SSE protocol specifics:

1. GET ``base_url`` → long-lived SSE stream
2. First ``event: endpoint`` frame gives the POST endpoint URL.
   Relative paths join with ``base_url``; absolute paths pass through.
3. Subsequent ``event: message`` frames carry JSON-RPC responses.
4. Client requests POST to the discovered endpoint.
"""

from __future__ import annotations



import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx
from httpx_sse import aconnect_sse

logger = logging.getLogger(__name__)


class McpTransportError(Exception):
    """Raised when a transport cannot send/recv."""


# Sentinel queued by the SSE reader loop when the stream dies, so recv()
# raises instead of blocking forever on an empty queue.
_SSE_CLOSED: dict[str, Any] = {"__sse_closed__": True}


class McpTransport(ABC):
    """Transport contract shared by stdio and SSE."""

    @abstractmethod
    async def start(self) -> None:
        """Open the transport (spawn child / open SSE / etc.)."""

    @abstractmethod
    async def stop(self) -> None:
        """Clean up. Idempotent."""

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """Push one JSON-RPC message to the peer."""

    @abstractmethod
    async def recv(self) -> dict[str, Any]:
        """Await the next JSON-RPC message from the peer."""


# --- stdio -----------------------------------------------------------------


class StdioTransport(McpTransport):
    """Spawn a child process and speak JSON-RPC line-by-line on stdin/stdout."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._process is not None:
            return
        merged_env = {**os.environ, **self.env}
        self._process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        # Drain stderr continuously — without a reader the child blocks once
        # the OS pipe buffer fills, deadlocking the whole transport.
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(), name=f"mcp-stderr-{self.command}"
        )

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while True:
                raw = await process.stderr.readline()
                if not raw:
                    break
                logger.debug(
                    "mcp_stderr command=%s line=%s",
                    self.command,
                    raw.decode("utf-8", errors="replace").rstrip(),
                )
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    async def stop(self) -> None:
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._stderr_task = None
        if self._process is None:
            return
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            if self._process is not None:
                self._process.kill()
        self._process = None

    async def send(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise McpTransportError("stdio transport not started")
        line = json.dumps(message) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()

    async def recv(self) -> dict[str, Any]:
        if self._process is None or self._process.stdout is None:
            raise McpTransportError("stdio transport not started")
        while True:
            raw = await self._process.stdout.readline()
            if not raw:
                raise McpTransportError("stdio transport closed by peer")
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data


# --- SSE / HTTP ------------------------------------------------------------


class SseTransport(McpTransport):
    """Connect to an MCP server over SSE (server→client) + HTTP POST (client→server).

    The first SSE frame whose ``event:`` field is ``endpoint`` carries the
    POST URL used for outgoing client-to-server messages.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        connect_timeout: float = 10.0,
    ) -> None:
        self.base_url = url
        self.headers = dict(headers or {})
        self.connect_timeout = connect_timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(connect_timeout))
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._endpoint_ready = asyncio.Event()
        self._endpoint_url: str | None = None
        self._cancel = asyncio.Event()

    @property
    def endpoint_url(self) -> str | None:
        return self._endpoint_url

    async def start(self) -> None:
        if self._reader_task is not None:
            return
        self._reader_task = asyncio.create_task(self._run_sse_loop())
        # Wait up to connect_timeout for endpoint discovery so the first
        # send has a target. Matches the semantic where send() errors
        # if endpoint_url is None.
        try:
            await asyncio.wait_for(
                self._endpoint_ready.wait(), timeout=self.connect_timeout
            )
        except asyncio.TimeoutError as exc:
            await self.stop()
            raise McpTransportError(
                f"MCP SSE endpoint discovery timed out for {_mask_url(self.base_url)}"
            ) from exc

    async def stop(self) -> None:
        self._cancel.set()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reader_task = None
        if self._owns_client:
            await self._client.aclose()

    async def send(self, message: dict[str, Any]) -> None:
        if self._endpoint_url is None:
            raise McpTransportError("SSE endpoint not yet discovered")
        response = await self._client.post(
            self._endpoint_url, json=message, headers=self.headers
        )
        if response.status_code >= 300:
            raise McpTransportError(
                f"SSE POST rejected: {response.status_code} {response.text[:200]}"
            )

    async def recv(self) -> dict[str, Any]:
        if self._reader_task is None:
            raise McpTransportError("SSE transport not started")
        item = await self._queue.get()
        if item is _SSE_CLOSED:
            # Re-queue the sentinel so every concurrent waiter unblocks.
            self._queue.put_nowait(_SSE_CLOSED)
            raise McpTransportError(
                f"MCP SSE stream closed for {_mask_url(self.base_url)}"
            )
        return item

    async def _run_sse_loop(self) -> None:
        try:
            async with aconnect_sse(
                self._client,
                "GET",
                self.base_url,
                headers=self.headers,
            ) as event_source:
                response = event_source.response
                if response.status_code >= 300:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise McpTransportError(
                        f"MCP SSE rejected (url={_mask_url(self.base_url)} "
                        f"status={response.status_code}): {body[:200]}"
                    )
                async for sse in event_source.aiter_sse():
                    if self._cancel.is_set():
                        break
                    event_name = sse.event or "message"
                    data = sse.data or ""
                    if event_name == "endpoint":
                        self._set_endpoint(data)
                    elif event_name == "message":
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, dict):
                            await self._queue.put(parsed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — surfaced via the sentinel below
            logger.debug("mcp_sse_loop_error url=%s error=%s", _mask_url(self.base_url), exc)
        finally:
            # Wake any recv() waiter — otherwise a dead SSE stream leaves
            # callers blocked on the queue forever.
            self._queue.put_nowait(_SSE_CLOSED)

    def _set_endpoint(self, raw: str) -> None:
        value = raw.strip()
        if not value:
            return
        if value.startswith(("http://", "https://")):
            self._endpoint_url = value
        else:
            base = httpx.URL(self.base_url)
            self._endpoint_url = str(base.join(value))
        self._endpoint_ready.set()


# --- Streamable HTTP -------------------------------------------------------


class StreamableHttpTransport(McpTransport):
    """MCP Streamable HTTP transport (spec 2025-03-26).

    Single endpoint: every JSON-RPC message is an HTTP POST. The server may
    reply with ``application/json`` or ``text/event-stream``. Session id from
    ``Mcp-Session-Id`` is echoed on subsequent requests.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        connect_timeout: float = 10.0,
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.connect_timeout = connect_timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(connect_timeout))
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._session_id: str | None = None
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False
        if self._owns_client:
            await self._client.aclose()

    def _request_headers(self) -> dict[str, str]:
        headers = {
            **self.headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def send(self, message: dict[str, Any]) -> None:
        if not self._started:
            raise McpTransportError("streamable HTTP transport not started")
        response = await self._client.post(
            self.url, json=message, headers=self._request_headers()
        )
        session = response.headers.get("mcp-session-id") or response.headers.get(
            "Mcp-Session-Id"
        )
        if session:
            self._session_id = session
        # Notifications / acks may return 202 with an empty body.
        if response.status_code == 202 or not response.content:
            if response.status_code >= 300:
                raise McpTransportError(
                    f"Streamable HTTP rejected: {response.status_code} "
                    f"{response.text[:200]}"
                )
            return
        if response.status_code >= 300:
            raise McpTransportError(
                f"Streamable HTTP rejected: {response.status_code} "
                f"{response.text[:200]}"
            )
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/event-stream" in content_type:
            for item in _iter_sse_json_objects(response.text):
                await self._queue.put(item)
            return
        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise McpTransportError(
                f"Streamable HTTP non-JSON body from {_mask_url(self.url)}"
            ) from exc
        if isinstance(data, dict):
            await self._queue.put(data)

    async def recv(self) -> dict[str, Any]:
        if not self._started:
            raise McpTransportError("streamable HTTP transport not started")
        return await self._queue.get()


def _iter_sse_json_objects(body: str) -> list[dict[str, Any]]:
    """Parse a finite SSE body into JSON-RPC dicts (data: lines)."""
    out: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip("\r")
        if line == "":
            if data_lines:
                payload = "\n".join(data_lines)
                data_lines = []
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    out.append(parsed)
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            parsed = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return out
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _mask_url(url: str) -> str:
    """Strip userinfo / query params so secrets don't leak in logs."""
    try:
        parsed = httpx.URL(url)
    except Exception:  # noqa: BLE001
        return url
    rebuilt = parsed.copy_with(username=None, password=None, query=None)
    return str(rebuilt)
