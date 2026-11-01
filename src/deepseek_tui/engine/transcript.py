"""Append-only record of the messages the model actually received.

Turn items exist for the UI; rebuilding model history from them is what let
tool inputs, ids and narration drift apart from what the model saw. This log
is written at the request boundary instead, so reminders, pruned bodies and
compaction snapshots are captured as sent, with their origin.

Each line replaces the tail of the history: ``state[:keep] + messages``. A round
that only appended stores only the new messages. ``commit`` closes a turn, and
a turn with requests but no commit (cancelled, failed) replays to its last
request, which is its last completed tool round.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from deepseek_tui.protocol.messages import Message

logger = logging.getLogger(__name__)

RecordKind = Literal["sync", "request", "commit"]


def _digest(dumped: dict[str, Any]) -> str:
    encoded = json.dumps(dumped, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class TranscriptState:
    """A replayed log. ``dumped`` holds the messages as written."""

    dumped: list[dict[str, Any]] = field(default_factory=list)
    # Messages sent this round but kept out of history once the turn commits.
    transient: list[int] = field(default_factory=list)
    turn_ids: list[str] = field(default_factory=list)
    last_seq: int = 0

    def messages(self) -> list[Message]:
        from deepseek_tui.engine.context_pressure import messages_from_dicts

        skipped = set(self.transient)
        return messages_from_dicts(
            item for index, item in enumerate(self.dumped) if index not in skipped
        )


def _read_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                records.append(json.loads(line))
            except ValueError:
                # Only a crash mid-append tears a line, and that is always the last one.
                logger.warning("transcript_torn_line path=%s", path)
    return records


def read_transcript(path: Path) -> TranscriptState | None:
    """Replay a log. None means no usable log, so the caller falls back."""
    try:
        records = _read_records(path)
    except OSError:
        return None
    if not records:
        return None
    effective: list[dict[str, Any]] = []
    for record in records:
        if record["type"] == "rollback":
            effective = [r for r in effective if r["seq"] <= record["to_seq"]]
        else:
            effective.append(record)
    state = TranscriptState(last_seq=records[-1]["seq"])
    for record in effective:
        state.dumped[record["keep"]:] = record["messages"]
        state.transient = record.get("transient", [])
        turn_id = record.get("turn_id")
        if turn_id and turn_id not in state.turn_ids:
            state.turn_ids.append(turn_id)
    return state


class Transcript:
    """Writer for one thread. Failures are logged; they never break a turn."""

    def __init__(self, path: Path) -> None:
        self.path = path
        state = read_transcript(path)
        self._seq = state.last_seq if state else 0
        self._digests = [_digest(item) for item in state.dumped] if state else []

    def record(
        self,
        kind: RecordKind,
        messages: list[Message],
        *,
        turn_id: str | None = None,
        round_idx: int | None = None,
        transient: list[int] | None = None,
    ) -> None:
        try:
            dumped = [message.model_dump(mode="json") for message in messages]
            digests = [_digest(item) for item in dumped]
            keep = 0
            for old, new in zip(self._digests, digests, strict=False):
                if old != new:
                    break
                keep += 1
            unchanged = keep == len(digests) == len(self._digests)
            if unchanged and kind == "sync":
                return
            self._append(
                {
                    "type": kind,
                    "turn_id": turn_id,
                    "round_idx": round_idx,
                    "keep": keep,
                    "messages": dumped[keep:],
                    "transient": transient or [],
                },
                durable=kind != "request",
            )
            self._digests = digests
        except (OSError, TypeError, ValueError):
            logger.warning("transcript_record_failed path=%s", self.path, exc_info=True)

    def rollback(self, kept_turn_ids: set[str]) -> None:
        """Forget every record after the last turn a rewind kept."""
        try:
            records = _read_records(self.path)
        except OSError:
            return
        target = 0
        live: list[dict[str, Any]] = []
        for record in records:
            if record["type"] == "rollback":
                live = [r for r in live if r["seq"] <= record["to_seq"]]
            else:
                live.append(record)
        for record in live:
            if record.get("turn_id") in kept_turn_ids:
                target = record["seq"]
        self._append({"type": "rollback", "to_seq": target}, durable=True)
        state = read_transcript(self.path)
        self._digests = [_digest(item) for item in state.dumped] if state else []

    def _append(self, record: dict[str, Any], *, durable: bool) -> None:
        self._seq += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("rb+" if self.path.exists() else "wb+") as stream:
            # Separate a crash-torn final line so it cannot swallow this record.
            if stream.seek(0, os.SEEK_END):
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    stream.write(b"\n")
            payload = {"seq": self._seq, **record}
            stream.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
