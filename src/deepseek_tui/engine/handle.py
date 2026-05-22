from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from deepseek_tui.engine.events import EngineEvent
from deepseek_tui.execpolicy.models import ApprovalDecision, ApprovalRequest

if TYPE_CHECKING:
    from deepseek_tui.hooks.dispatcher import HookDispatcher


# --- Ops (formerly engine/ops.py) -------------------------------------------


@dataclass(frozen=True, slots=True)
class SendMessageOp:
    content: str
    model: str | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class CancelRequestOp:
    reason: str = "user_cancelled"


EngineOp = SendMessageOp | CancelRequestOp


# --- Approval handlers (formerly engine/approval.py) -------------------------


class ApprovalHandler:
    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        raise NotImplementedError


class AutoApprovalHandler(ApprovalHandler):
    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        return ApprovalDecision.APPROVED


class DenyApprovalHandler(ApprovalHandler):
    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        return ApprovalDecision.DENIED


# --- EngineHandle ------------------------------------------------------------


class EngineHandle:
    def __init__(self, hooks: HookDispatcher | None = None) -> None:
        self._op_queue: asyncio.Queue[EngineOp] = asyncio.Queue()
        self._event_queue: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=4096)
        self.cancel_event = asyncio.Event()
        self.pending_user_inputs: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._steer_queue: asyncio.Queue[str] = asyncio.Queue()
        self._hooks = hooks
        self._response_id: str | None = None
        # True while Engine is actively processing a turn (between
        # SendMessageOp pickup and TurnComplete/TurnCancelled emit). Read
        # by the TUI to decide whether composer submit should send a new
        # SendMessageOp or queue a steer onto the live turn.
        self._turn_active = asyncio.Event()

    @property
    def hooks(self) -> HookDispatcher | None:
        return self._hooks

    def attach_hooks(self, hooks: HookDispatcher) -> None:
        """Attach a hook dispatcher (no-op if one is already set)."""
        if self._hooks is None:
            self._hooks = hooks

    def set_response_id(self, response_id: str) -> None:
        self._response_id = response_id

    def clear_response_id(self) -> None:
        self._response_id = None

    async def send_message(
        self,
        content: str,
        model: str | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> None:
        await self.send_op(
            SendMessageOp(
                content=content,
                model=model,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
        )

    async def send_op(self, op: EngineOp) -> None:
        await self._op_queue.put(op)

    async def next_op(self) -> EngineOp:
        return await self._op_queue.get()

    async def emit(self, event: EngineEvent) -> None:
        await self._event_queue.put(event)
        if self._hooks is not None:
            await self._bridge_to_hooks(event)

    def try_emit(self, event: EngineEvent) -> bool:
        """Enqueue without blocking. Returns False if the queue is full.

        Used by background drainer tasks so a slow/absent consumer cannot
        wedge producers or grow unbounded mailbox backlogs.
        """
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        # Never spawn hook tasks from background drainer paths — hooks can
        # shell out and leak processes/tasks when the consumer is slow.
        return True

    def drain_events(self) -> list[EngineEvent]:
        """Non-blocking drain (tests and shutdown cleanup)."""
        out: list[EngineEvent] = []
        while True:
            try:
                out.append(self._event_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out

    async def _bridge_to_hooks(self, event: EngineEvent) -> None:
        """Translate EngineEvent → HookEvent and broadcast (best-effort)."""
        from deepseek_tui.engine.events import (
            ApprovalRequiredEvent,
            ApprovalResolvedEvent,
            SessionEndedEvent,
            SessionStartedEvent,
            TextDeltaEvent,
            ThinkingDeltaEvent,
            ToolCallEvent,
            ToolResultEvent,
            TurnCancelledEvent,
            TurnCompleteEvent,
            TurnStartedEvent,
        )
        from deepseek_tui.hooks.events import (
            ApprovalLifecycleEvent,
            ResponseDeltaEvent,
            ResponseEndEvent,
            ResponseStartEvent,
            SessionLifecycleEvent,
            ToolLifecycleEvent,
        )

        hook_event = None
        rid = self._response_id
        if isinstance(event, TurnStartedEvent) and rid is not None:
            hook_event = ResponseStartEvent(response_id=rid)
        elif isinstance(event, TextDeltaEvent) and rid is not None:
            hook_event = ResponseDeltaEvent(response_id=rid, delta=event.text)
        elif isinstance(event, ThinkingDeltaEvent) and rid is not None:
            hook_event = ResponseDeltaEvent(
                response_id=rid, delta=f"[thinking]{event.thinking}"
            )
        elif isinstance(event, (TurnCompleteEvent, TurnCancelledEvent)) and rid is not None:
            hook_event = ResponseEndEvent(response_id=rid)
        elif isinstance(event, ToolCallEvent):
            hook_event = ToolLifecycleEvent(
                response_id=event.tool_call.id,
                tool_name=event.tool_call.name,
                phase="start",
                payload={"arguments": event.tool_call.arguments},
            )
        elif isinstance(event, ToolResultEvent):
            hook_event = ToolLifecycleEvent(
                response_id=event.tool_call_id,
                tool_name=event.tool_name,
                phase="complete" if event.success else "error",
                payload={"success": event.success},
            )
        elif isinstance(event, SessionStartedEvent):
            hook_event = SessionLifecycleEvent(
                session_id=event.session_id, phase="start"
            )
        elif isinstance(event, SessionEndedEvent):
            hook_event = SessionLifecycleEvent(
                session_id=event.session_id, phase="end", turns=event.turns
            )
        elif isinstance(event, ApprovalRequiredEvent):
            hook_event = ApprovalLifecycleEvent(
                approval_id=event.tool_call_id,
                phase="requested",
                reason=getattr(event.request, "reason", None),
            )
        elif isinstance(event, ApprovalResolvedEvent):
            hook_event = ApprovalLifecycleEvent(
                approval_id=event.tool_call_id,
                phase="resolved",
                reason=event.reason,
            )
        if hook_event is not None:
            try:
                await self._hooks.emit(hook_event)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass

    async def events(self) -> AsyncIterator[EngineEvent]:
        while True:
            yield await self._event_queue.get()

    async def cancel(self, reason: str = "user_cancelled") -> None:
        self.cancel_event.set()
        await self.send_op(CancelRequestOp(reason=reason))

    def reset_cancel(self) -> None:
        self.cancel_event = asyncio.Event()

    async def steer(self, text: str) -> None:
        """Inject a user message mid-turn (mirrors Rust rx_steer)."""
        await self._steer_queue.put(text)

    def is_turn_active(self) -> bool:
        """True between SendMessageOp pickup and TurnComplete/TurnCancelled.

        TUI uses this to choose between ``send_op(SendMessageOp(...))`` and
        ``steer(...)`` when the user submits the composer. ``steer`` is the
        right call while a turn is live: the message is queued onto the
        running turn and Engine drains it at the top of its next round.
        """
        return self._turn_active.is_set()

    def _mark_turn_active(self) -> None:
        self._turn_active.set()

    def _mark_turn_idle(self) -> None:
        self._turn_active.clear()

    def drain_steers(self) -> list[str]:
        """Non-blocking drain of all queued steer messages."""
        steers: list[str] = []
        while True:
            try:
                steers.append(self._steer_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return steers

    def resolve_user_input(self, tool_call_id: str, response: dict[str, Any]) -> bool:
        """Resolve a pending user input request from the TUI.

        Returns True if the future was found and resolved.
        """
        future = self.pending_user_inputs.get(tool_call_id)
        if future is not None and not future.done():
            future.set_result(response)
            return True
        return False
