"""Hook sinks for event emission."""

from __future__ import annotations

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
        """Emit event to stdout."""
        payload = event_to_dict(event)
        print(json.dumps(payload), flush=True)


class JsonlHookSink(HookSink):
    """Append hook events to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def emit(self, event: HookEvent) -> None:
        """Append event to JSONL file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event_to_dict(event),
        }
        line = json.dumps(payload) + "\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)


class WebhookHookSink(HookSink):
    """POST hook events to a webhook URL."""

    def __init__(self, url: str, max_retries: int = 2) -> None:
        self.url = url
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def emit(self, event: HookEvent) -> None:
        """POST event to webhook with retries."""
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
            await httpx.AsyncClient().aclose()  # brief backoff
            import asyncio

            await asyncio.sleep(0.2 * retries)

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
