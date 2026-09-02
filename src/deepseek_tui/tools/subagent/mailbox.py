"""Sub-agent mailbox — structured progress/lifecycle event stream.

Sequence
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


# Bound spawn prompt on ``started`` so SSE stays light while dock/list UIs
# can still show a distinctive one-line title per sub-agent.
_MAILBOX_PROMPT_CHARS = 500


def _clip_mailbox_prompt(prompt: str | None) -> str | None:
    if prompt is None:
        return None
    text = " ".join(prompt.split()).strip()
    if not text:
        return None
    if len(text) <= _MAILBOX_PROMPT_CHARS:
        return text
    return text[: _MAILBOX_PROMPT_CHARS - 1].rstrip() + "…"


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
    # Provider tool-call id: disambiguates parallel same-name calls that share
    # one ``step`` round number (Workbench step ids key off this when present).
    tool_call_id: str | None = None
    ok: bool | None = None
    parent_id: str | None = None
    summary: str | None = None
    error: str | None = None
    model: str | None = None
    usage: dict[str, Any] | None = None
    # Truncated tool I/O for Workbench step-flow expand (not full payloads).
    input_summary: str | None = None
    output_summary: str | None = None
    # Spawn assignment preview for Workbench dock / list titles.
    prompt: str | None = None

    @staticmethod
    def started(
        agent_id: str, agent_type: str, prompt: str | None = None
    ) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.STARTED,
            agent_id=agent_id,
            agent_type=agent_type,
            prompt=_clip_mailbox_prompt(prompt),
        )

    @staticmethod
    def progress(agent_id: str, status: str) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.PROGRESS, agent_id=agent_id, status=status
        )

    @staticmethod
    def tool_call_started(
        agent_id: str,
        tool_name: str,
        step: int,
        *,
        tool_call_id: str | None = None,
        input_summary: str | None = None,
    ) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.TOOL_CALL_STARTED,
            agent_id=agent_id,
            tool_name=tool_name,
            step=step,
            tool_call_id=tool_call_id,
            input_summary=input_summary,
        )

    @staticmethod
    def tool_call_completed(
        agent_id: str,
        tool_name: str,
        step: int,
        ok: bool,
        *,
        tool_call_id: str | None = None,
        input_summary: str | None = None,
        output_summary: str | None = None,
    ) -> MailboxMessage:
        return MailboxMessage(
            kind=MailboxMessageKind.TOOL_CALL_COMPLETED,
            agent_id=agent_id,
            tool_name=tool_name,
            step=step,
            tool_call_id=tool_call_id,
            ok=ok,
            input_summary=input_summary,
            output_summary=output_summary,
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
    """Sender side of the mailbox.

    The same instance is shared by child runtimes so all producers
    publish into one stream; consumers poll it via ``drain_available``.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[MailboxEnvelope] = asyncio.Queue(
            maxsize=MAILBOX_MAX_ENVELOPES
        )
        self._seq = 0
        self._closed = False

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
        """Close the mailbox; further sends are dropped."""
        self._closed = True

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
