"""MCP startup preload — background tool discovery after serve starts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PRELOAD_TIMEOUT_S = 30.0


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class McpPreloadSnapshot:
    """Point-in-time preload status for HTTP / diagnostics."""

    phase: str = "idle"
    enabled_servers: int = 0
    connected_servers: int = 0
    tools_count: int = 0
    from_disk_cache: bool = False
    started_at_ms: int | None = None
    completed_at_ms: int | None = None
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        warming = self.phase == "warming"
        ready = self.phase in ("ready", "partial") or (
            self.tools_count > 0 and self.phase != "failed"
        )
        return {
            "phase": self.phase,
            "warming": warming,
            "ready": ready,
            "enabled_servers": self.enabled_servers,
            "connected_servers": self.connected_servers,
            "tools_count": self.tools_count,
            "from_disk_cache": self.from_disk_cache,
            "started_at_ms": self.started_at_ms,
            "completed_at_ms": self.completed_at_ms,
            "error": self.error,
        }


@dataclass
class McpPreloadTracker:
    phase: str = "idle"
    from_disk_cache: bool = False
    started_at_ms: int | None = None
    completed_at_ms: int | None = None
    error: str | None = None
    _task: Any = field(default=None, repr=False)

    def mark_ready_from_disk(self, *, tools_count: int, enabled_servers: int) -> None:
        self.phase = "ready"
        self.from_disk_cache = True
        self.completed_at_ms = _now_ms()
        self.error = None

    def snapshot(
        self,
        *,
        enabled_servers: int,
        connected_servers: int,
        tools_count: int,
    ) -> McpPreloadSnapshot:
        return McpPreloadSnapshot(
            phase=self.phase,
            enabled_servers=enabled_servers,
            connected_servers=connected_servers,
            tools_count=tools_count,
            from_disk_cache=self.from_disk_cache,
            started_at_ms=self.started_at_ms,
            completed_at_ms=self.completed_at_ms,
            error=self.error,
        )
