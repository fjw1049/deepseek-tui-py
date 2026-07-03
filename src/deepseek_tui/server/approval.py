"""Approval and elevation bridges.
"""

from __future__ import annotations



# HTTP-suspended tool approvals for headless / GUI runtimes.
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from deepseek_tui.engine.handle import ApprovalHandler
from deepseek_tui.policy.approval import ApprovalDecision, ApprovalRequest

AutoApproveFn = Callable[[], Awaitable[bool]]


@dataclass(slots=True)
class PendingApprovalRecord:
    thread_id: str
    tool_name: str
    description: str
    input_summary: str = ""
    impacts: list[str] = field(default_factory=list)
    presentation_risk: str = ""
    approval_key: str = ""


@dataclass
class ApprovalBridge:
    """Maps approval_id → Future[bool] until POST /v1/approvals/{id}."""

    _pending: dict[str, asyncio.Future[bool]] = field(default_factory=dict)
    _meta: dict[str, PendingApprovalRecord] = field(default_factory=dict)
    _remember: dict[str, bool] = field(default_factory=dict)

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

    def resolve(self, approval_id: str, approved: bool, *, remember: bool = False) -> bool:
        fut = self._pending.pop(approval_id, None)
        self._meta.pop(approval_id, None)
        if fut is None or fut.done():
            self._remember.pop(approval_id, None)
            return False
        if approved and remember:
            self._remember[approval_id] = True
        else:
            self._remember.pop(approval_id, None)
        fut.set_result(approved)
        return True

    def consume_remember(self, approval_id: str) -> bool:
        return self._remember.pop(approval_id, False)

    def list_pending(self, thread_id: str | None = None) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
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
                    "input_summary": meta.input_summary if meta else "",
                    "impacts": list(meta.impacts) if meta else [],
                    "risk": meta.presentation_risk if meta else "",
                    "risk_level": (
                        "high"
                        if meta and meta.presentation_risk == "destructive"
                        else "low"
                    ),
                    "approval_key": meta.approval_key if meta else "",
                }
            )
        return out

    def cancel_for_thread(self, thread_id: str) -> None:
        """Cancel all pending approvals belonging to a specific thread."""
        to_cancel: list[str] = []
        for approval_id, fut in self._pending.items():
            if fut.done():
                continue
            meta = self._meta.get(approval_id)
            if meta is not None and meta.thread_id == thread_id:
                to_cancel.append(approval_id)
        for approval_id in to_cancel:
            fut = self._pending.pop(approval_id, None)
            self._meta.pop(approval_id, None)
            self._remember.pop(approval_id, None)
            if fut is not None and not fut.done():
                fut.cancel()

    def cancel_all(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        self._meta.clear()
        self._remember.clear()


class HttpApprovalHandler(ApprovalHandler):
    """Block Engine tool approval until POST /v1/approvals/{id}.

    Resolves via :class:`ApprovalBridge`.
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

    async def auto_approve_enabled(self) -> bool:
        return self._auto_approve is not None and await self._auto_approve()

    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        if await self.auto_approve_enabled():
            return ApprovalDecision.APPROVED
        summary = (
            request.title
            or request.primary_preview
            or request.input_summary
            or request.reason
            or ""
        )
        fut = self._bridge.register(
            tool_call_id,
            meta=PendingApprovalRecord(
                thread_id=self._thread_id,
                tool_name=request.tool_name,
                description=request.title or summary,
                input_summary=request.input_summary or request.primary_preview,
                impacts=list(request.impacts),
                presentation_risk=request.presentation_risk,
                approval_key=request.approval_key,
            ),
        )
        try:
            approved = await fut
        except asyncio.CancelledError:
            return ApprovalDecision.DENIED
        if not approved:
            return ApprovalDecision.DENIED
        if self._bridge.consume_remember(tool_call_id):
            return ApprovalDecision.APPROVED_SESSION
        return ApprovalDecision.APPROVED


# HTTP-suspended sandbox elevation for Workbench / headless runtimes.


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

    def cancel_for_thread(self, thread_id: str) -> None:
        """Cancel all pending elevations belonging to a specific thread."""
        to_cancel = [
            elevation_id
            for elevation_id, fut in self._pending.items()
            if not fut.done()
            and (meta := self._meta.get(elevation_id)) is not None
            and meta.thread_id == thread_id
        ]
        for elevation_id in to_cancel:
            fut = self._pending.pop(elevation_id, None)
            self._meta.pop(elevation_id, None)
            if fut is not None and not fut.done():
                fut.cancel()

    def cancel_all(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        self._meta.clear()
