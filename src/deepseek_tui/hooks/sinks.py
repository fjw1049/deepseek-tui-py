"""Hook sinks for event emission.

Mirrors ``crates/hooks/src/lib.rs`` (170 lines). Three sinks:

- :class:`StdoutHookSink`: prints JSON events line-by-line
- :class:`JsonlHookSink`: appends timestamped events to a JSONL log file
- :class:`WebhookHookSink`: POSTs events to a URL with backoff retry
  (max 2 retries, 200ms × attempt backoff — Rust parity)
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from deepseek_tui.hooks.events import HookEvent, event_to_dict


class HookSink(ABC):
    """Abstract base for hook event sinks."""

    @abstractmethod
    async def emit(self, event: HookEvent) -> None:
        """Emit a hook event."""
        ...


class StdoutHookSink(HookSink):
    """Emit hook events to stdout as JSON."""

    async def emit(self, event: HookEvent) -> None:
        payload = event_to_dict(event)
        print(json.dumps(payload), flush=True)


class JsonlHookSink(HookSink):
    """Append hook events to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def emit(self, event: HookEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event_to_dict(event),
        }
        line = json.dumps(payload) + "\n"
        await asyncio.to_thread(self._write_line, line)

    def _write_line(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)


class WebhookHookSink(HookSink):
    """POST hook events to a webhook URL.

    Mirrors Rust ``WebhookHookSink`` (lib.rs:108-153): max 2 retries,
    200ms × retries backoff. Status != 2xx triggers retry.
    """

    def __init__(self, url: str, max_retries: int = 2) -> None:
        self.url = url
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def emit(self, event: HookEvent) -> None:
        client = await self._get_client()
        payload: dict[str, Any] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event_to_dict(event),
        }
        retries = 0
        while True:
            try:
                resp = await client.post(self.url, json=payload)
                if resp.is_success:
                    return
                if retries >= self.max_retries:
                    raise RuntimeError(
                        f"webhook returned non-success status {resp.status_code}"
                    )
            except httpx.HTTPError as e:
                if retries >= self.max_retries:
                    raise RuntimeError(f"webhook request failed: {e}") from e
            retries += 1
            await asyncio.sleep(0.2 * retries)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class ShellHookSink(HookSink):
    """Execute a shell command when a matching event fires.

    Mirrors Rust HookExecutor — runs command with event JSON on stdin,
    respects timeout. Only fires for events matching ``event_filter``.
    """

    def __init__(
        self, event_filter: str, command: str, timeout: float = 30.0
    ) -> None:
        self.event_filter = event_filter
        self.command = command
        self.timeout = timeout

    async def emit(self, event: HookEvent) -> None:
        event_dict = event_to_dict(event)
        if event_dict.get("type") != self.event_filter:
            return
        stdin_data = json.dumps(event_dict).encode()
        try:
            proc = await asyncio.create_subprocess_shell(
                self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
        except OSError:
            pass
