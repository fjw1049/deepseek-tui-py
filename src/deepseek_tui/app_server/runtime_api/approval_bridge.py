"""HTTP-suspended tool approvals for headless / GUI runtimes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from deepseek_tui.engine.handle import ApprovalHandler
from deepseek_tui.execpolicy.models import ApprovalDecision, ApprovalRequest

AutoApproveFn = Callable[[], Awaitable[bool]]


@dataclass(slots=True)
class PendingApprovalRecord:
    thread_id: str
    tool_name: str
    description: str


@dataclass
class ApprovalBridge:
    """Maps approval_id → Future[bool] until POST /v1/approvals/{id}."""

    _pending: dict[str, asyncio.Future[bool]] = field(default_factory=dict)
    _meta: dict[str, PendingApprovalRecord] = field(default_factory=dict)

    def register(
        self,
        approval_id: str,
        *,
        meta: PendingApprovalRecord | None = None,
    ) -> asyncio.Future[bool]:
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = fut
        if meta is not None:
            self._meta[approval_id] = meta
        return fut

    def resolve(self, approval_id: str, approved: bool) -> bool:
        fut = self._pending.pop(approval_id, None)
        self._meta.pop(approval_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True

    def list_pending(self, thread_id: str | None = None) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for approval_id, fut in self._pending.items():
            if fut.done():
                continue
            meta = self._meta.get(approval_id)
            if thread_id and (meta is None or meta.thread_id != thread_id):
                continue
            out.append(
                {
                    "approval_id": approval_id,
                    "id": approval_id,
                    "thread_id": meta.thread_id if meta else "",
                    "tool_name": meta.tool_name if meta else "",
                    "description": meta.description if meta else "",
                    "summary": meta.description if meta else "",
                }
            )
        return out

    def cancel_all(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        self._meta.clear()


class HttpApprovalHandler(ApprovalHandler):
    """Block Engine tool approval until POST /v1/approvals/{id}.

    Mirrors TUI ``TUIApprovalHandler`` but resolves via :class:`ApprovalBridge`.
    """

    def __init__(
        self,
        bridge: ApprovalBridge,
        *,
        thread_id: str = "",
        auto_approve: AutoApproveFn | None = None,
    ) -> None:
        self._bridge = bridge
        self._thread_id = thread_id
        self._auto_approve = auto_approve

    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        if self._auto_approve is not None and await self._auto_approve():
            return ApprovalDecision.APPROVED
        fut = self._bridge.register(
            tool_call_id,
            meta=PendingApprovalRecord(
                thread_id=self._thread_id,
                tool_name=request.tool_name,
                description=request.reason or request.input_summary or "",
            ),
        )
        try:
            approved = await fut
        except asyncio.CancelledError:
            return ApprovalDecision.DENIED
        return (
            ApprovalDecision.APPROVED
            if approved
            else ApprovalDecision.DENIED
        )
