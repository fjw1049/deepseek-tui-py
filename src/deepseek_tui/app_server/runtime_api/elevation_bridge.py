"""HTTP-suspended sandbox elevation for Workbench / headless runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(slots=True)
class PendingElevationRecord:
    thread_id: str
    tool_name: str
    reason: str
    elevation_kind: str
    command_preview: str = ""


@dataclass
class ElevationBridge:
    """Maps tool_call_id → Future[bool] until POST /v1/elevations/{id}."""

    _pending: dict[str, asyncio.Future[bool]] = field(default_factory=dict)
    _meta: dict[str, PendingElevationRecord] = field(default_factory=dict)

    def register(
        self,
        elevation_id: str,
        *,
        meta: PendingElevationRecord | None = None,
    ) -> asyncio.Future[bool]:
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[elevation_id] = fut
        if meta is not None:
            self._meta[elevation_id] = meta
        return fut

    def resolve(self, elevation_id: str, approved: bool) -> bool:
        fut = self._pending.pop(elevation_id, None)
        self._meta.pop(elevation_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True

    def list_pending(self, thread_id: str | None = None) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for elevation_id, fut in self._pending.items():
            if fut.done():
                continue
            meta = self._meta.get(elevation_id)
            if thread_id and (meta is None or meta.thread_id != thread_id):
                continue
            out.append(
                {
                    "elevation_id": elevation_id,
                    "tool_call_id": elevation_id,
                    "thread_id": meta.thread_id if meta else "",
                    "tool_name": meta.tool_name if meta else "",
                    "reason": meta.reason if meta else "",
                    "elevation_kind": meta.elevation_kind if meta else "",
                    "command_preview": meta.command_preview if meta else "",
                }
            )
        return out

    def cancel_all(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        self._meta.clear()
