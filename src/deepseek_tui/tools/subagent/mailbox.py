"""Sub-agent mailbox — structured progress/lifecycle event stream.

Mirrors ``crates/tui/src/tools/subagent/mailbox.rs`` (478 lines). Sequence
numbers are monotonic across the whole mailbox so consumers see a single
consistent ordering even with multiple producers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any


class MailboxMessageKind(str, Enum):
    STARTED = "started"
    PROGRESS = "progress"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    CHILD_SPAWNED = "child_spawned"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TOKEN_USAGE = "token_usage"


@dataclass(slots=True, frozen=True)
class MailboxMessage:
    """Structured progress envelope.

    Tagged union keyed by :attr:`kind`. Only the fields relevant to the
    kind are populated; other fields are ``None``.
    """

    kind: MailboxMessageKind
    agent_id: str
    agent_type: str | None = None
    status: str | None = None
    tool_name: str | None = None
    step: int | None = None
    ok: bool | None = None
    parent_id: str | None = None
    summary: str | None = None
    error: str | None = None
    model: str | None = None
    usage: dict[str, Any] | None = None

    @staticmethod
    def started(agent_id: str, agent_type: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.STARTED,
            agent_id=agent_id,
            agent_type=agent_type,
        )

    @staticmethod
    def progress(agent_id: str, status: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.PROGRESS, agent_id=agent_id, status=status
        )

    @staticmethod
    def tool_call_started(agent_id: str, tool_name: str, step: int) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.TOOL_CALL_STARTED,
            agent_id=agent_id,
            tool_name=tool_name,
            step=step,
        )

    @staticmethod
    def tool_call_completed(
        agent_id: str, tool_name: str, step: int, ok: bool
    ) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.TOOL_CALL_COMPLETED,
            agent_id=agent_id,
            tool_name=tool_name,
            step=step,
            ok=ok,
        )

    @staticmethod
    def child_spawned(parent_id: str, child_id: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.CHILD_SPAWNED,
            agent_id=child_id,
            parent_id=parent_id,
        )

    @staticmethod
    def completed(agent_id: str, summary: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.COMPLETED, agent_id=agent_id, summary=summary
        )

    @staticmethod
    def failed(agent_id: str, error: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.FAILED, agent_id=agent_id, error=error
        )

    @staticmethod
    def cancelled(agent_id: str) -> MailboxMessage:
        return MailboxMessage(kind=MailboxMessageKind.CANCELLED, agent_id=agent_id)

    @staticmethod
    def token_usage(
        agent_id: str, model: str, usage: dict[str, Any]
    ) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.TOKEN_USAGE,
            agent_id=agent_id,
            model=model,
            usage=usage,
        )


@dataclass(slots=True, frozen=True)
class MailboxEnvelope:
    seq: int
    message: MailboxMessage


MAILBOX_MAX_ENVELOPES = 512


class Mailbox:
    """Sender side of the mailbox. Cheaply sharable via ``share()``.

    Mirrors Rust ``Mailbox`` (mailbox.rs:135-). In Rust this is ``Clone``
    through an ``Arc``; here we expose ``share()`` which returns the same
    underlying object so child runtimes observing the same stream stay
    in sync.
    """

    def __init__(self, cancel_token: asyncio.Event | None = None) -> None:
        self._queue: asyncio.Queue[MailboxEnvelope] = asyncio.Queue(
            maxsize=MAILBOX_MAX_ENVELOPES
        )
        self._seq = 0
        self._closed = False
        self._cancel_token = cancel_token or asyncio.Event()

    @property
    def cancel_token(self) -> asyncio.Event:
        return self._cancel_token

    def share(self) -> Mailbox:
        """Return this mailbox so child producers publish into the same stream."""
        return self

    def is_closed(self) -> bool:
        return self._closed

    def send(self, message: MailboxMessage) -> bool:
        """Enqueue a message with a fresh monotonic seq.

        Returns False if the mailbox is already closed.
        """
        if self._closed:
            return False
        self._seq += 1
        envelope = MailboxEnvelope(seq=self._seq, message=message)
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull:
            # Drop oldest progress so lifecycle events can still land.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(envelope)
            except asyncio.QueueEmpty:
                return False
        return True

    def close(self) -> None:
        """Close the mailbox and cancel the bound token.

        Per Rust behavior: closing signals cancellation through the shared
        token so children cooperating on the same token shut down too.
        """
        if self._closed:
            return
        self._closed = True
        self._cancel_token.set()

    async def recv(self) -> MailboxEnvelope | None:
        """Receive next envelope. Returns None if closed and queue drained."""
        if self._closed and self._queue.empty():
            return None
        try:
            return await self._queue.get()
        except asyncio.CancelledError:
            return None

    def try_recv(self) -> MailboxEnvelope | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def drain_available(self) -> list[MailboxEnvelope]:
        """Non-blocking drain of everything already enqueued."""
        out: list[MailboxEnvelope] = []
        while True:
            envelope = self.try_recv()
            if envelope is None:
                return out
            out.append(envelope)
