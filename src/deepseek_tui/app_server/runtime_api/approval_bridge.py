"""HTTP-suspended tool approvals for headless / GUI runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class ApprovalBridge:
    """Maps approval_id → Future[bool] until POST /v1/approvals/{id}."""

    _pending: dict[str, asyncio.Future[bool]] = field(default_factory=dict)

    def register(self, approval_id: str) -> asyncio.Future[bool]:
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = fut
        return fut

    def resolve(self, approval_id: str, approved: bool) -> bool:
        fut = self._pending.pop(approval_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True

    def cancel_all(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
