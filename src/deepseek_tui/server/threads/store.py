"""File-based persistence for threads/turns/items (JSON) and events (JSONL).

Mirrors Rust ``RuntimeThreadStore`` (runtime_threads.rs:191-476). Pure I/O —
no engine logic lives here.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.server.threads.models import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    RuntimeEventRecord,
    RuntimeStoreState,
    ThreadRecord,
    TurnItemRecord,
    TurnRecord,
)
from deepseek_tui.utils import write_json_atomic

logger = logging.getLogger(__name__)


class RuntimeThreadStore:
    """File-based store: threads/turns/items as individual JSON, events as JSONL.

    Mirrors Rust ``RuntimeThreadStore`` (line 191-476).
    """

    def __init__(self, root: Path) -> None:
        self._threads_dir = root / "threads"
        self._turns_dir = root / "turns"
        self._items_dir = root / "items"
        self._events_dir = root / "events"
        self._state_path = root / "state.json"

        for d in (
            self._threads_dir,
            self._turns_dir,
            self._items_dir,
            self._events_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        if self._state_path.exists():
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._state = RuntimeStoreState.model_validate(raw)
        else:
            self._state = RuntimeStoreState()
            write_json_atomic(self._state_path, self._state.model_dump())

        import asyncio

        self._seq_lock = asyncio.Lock()
        # Per-thread locks so seq allocation + JSONL append happen atomically
        # for a given events file (concurrent writers would interleave lines).
        self._event_write_locks: dict[str, asyncio.Lock] = {}
        self._events_since_checkpoint = 0
        self._last_checkpoint_at = time.monotonic()

    CHECKPOINT_EVENT_INTERVAL = 16
    CHECKPOINT_MAX_INTERVAL_S = 0.5

    # --- paths ---------------------------------------------------------------

    def _thread_path(self, thread_id: str) -> Path:
        return self._threads_dir / f"{thread_id}.json"

    def _turn_path(self, turn_id: str) -> Path:
        return self._turns_dir / f"{turn_id}.json"

    def _item_path(self, item_id: str) -> Path:
        return self._items_dir / f"{item_id}.json"

    def _events_path(self, thread_id: str) -> Path:
        return self._events_dir / f"{thread_id}.jsonl"

    # --- CRUD ----------------------------------------------------------------

    def save_thread(self, thread: ThreadRecord) -> None:
        write_json_atomic(self._thread_path(thread.id), thread.model_dump(mode="json"))

    def save_turn(self, turn: TurnRecord) -> None:
        write_json_atomic(self._turn_path(turn.id), turn.model_dump(mode="json"))

    def save_item(self, item: TurnItemRecord) -> None:
        write_json_atomic(self._item_path(item.id), item.model_dump(mode="json"))

    def delete_turn(self, turn_id: str) -> None:
        self._turn_path(turn_id).unlink(missing_ok=True)

    def delete_item(self, item_id: str) -> None:
        self._item_path(item_id).unlink(missing_ok=True)

    def load_thread(self, thread_id: str) -> ThreadRecord:
        path = self._thread_path(thread_id)
        if not path.exists():
            raise FileNotFoundError(f"Thread not found: {thread_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = ThreadRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Thread schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def load_turn(self, turn_id: str) -> TurnRecord:
        path = self._turn_path(turn_id)
        if not path.exists():
            raise FileNotFoundError(f"Turn not found: {turn_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = TurnRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Turn schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def load_item(self, item_id: str) -> TurnItemRecord:
        path = self._item_path(item_id)
        if not path.exists():
            raise FileNotFoundError(f"Item not found: {item_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = TurnItemRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Item schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def list_threads(self) -> list[ThreadRecord]:
        out: list[ThreadRecord] = []
        if not self._threads_dir.exists():
            return out
        for path in self._threads_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = ThreadRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Thread schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            out.append(record)
        out.sort(key=lambda t: t.updated_at, reverse=True)
        return out

    def list_turns_for_thread(self, thread_id: str) -> list[TurnRecord]:
        out: list[TurnRecord] = []
        if not self._turns_dir.exists():
            return out
        for path in self._turns_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = TurnRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Turn schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            if record.thread_id == thread_id:
                out.append(record)
        out.sort(key=lambda t: t.created_at)
        return out

    def list_items_for_turn(self, turn_id: str) -> list[TurnItemRecord]:
        out: list[TurnItemRecord] = []
        if not self._items_dir.exists():
            return out
        try:
            turn = self.load_turn(turn_id)
        except FileNotFoundError:
            turn = None
        if turn is not None and turn.item_ids:
            for item_id in turn.item_ids:
                try:
                    out.append(self.load_item(item_id))
                except FileNotFoundError:
                    continue
            return out
        for path in self._items_dir.glob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = TurnItemRecord.model_validate(raw)
            if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
                raise ValueError(
                    f"Item schema v{record.schema_version} is newer than supported "
                    f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
                )
            if record.turn_id == turn_id:
                out.append(record)
        out.sort(key=lambda i: i.started_at or datetime.min.replace(tzinfo=timezone.utc))
        return out

    # --- events (JSONL append) -----------------------------------------------

    async def append_event(
        self,
        thread_id: str,
        turn_id: str | None,
        item_id: str | None,
        event: str,
        payload: dict[str, Any],
        *,
        force_checkpoint: bool = False,
    ) -> RuntimeEventRecord:
        import asyncio

        write_lock = self._event_write_locks.setdefault(thread_id, asyncio.Lock())
        # Hold the per-thread lock across seq allocation AND the JSONL append
        # so concurrent writers cannot interleave lines in the events file.
        async with write_lock:
            async with self._seq_lock:
                seq = self._state.next_seq
                self._state.next_seq += 1
                self._events_since_checkpoint += 1
                now = time.monotonic()
                checkpoint_due = force_checkpoint or (
                    self._events_since_checkpoint >= self.CHECKPOINT_EVENT_INTERVAL
                    or (now - self._last_checkpoint_at) >= self.CHECKPOINT_MAX_INTERVAL_S
                )
                if checkpoint_due:
                    write_json_atomic(self._state_path, self._state.model_dump())
                    self._events_since_checkpoint = 0
                    self._last_checkpoint_at = now

            record = RuntimeEventRecord(
                schema_version=CURRENT_RUNTIME_SCHEMA_VERSION,
                seq=seq,
                timestamp=datetime.now(timezone.utc),
                thread_id=thread_id,
                turn_id=turn_id,
                item_id=item_id,
                event=event,
                payload=payload,
            )

            path = self._events_path(thread_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            line = record.model_dump_json()
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                if checkpoint_due:
                    f.flush()

        return record

    async def flush_event_checkpoint(self) -> None:
        """Persist ``state.next_seq`` after a batched delta flush."""
        async with self._seq_lock:
            if self._events_since_checkpoint <= 0:
                return
            write_json_atomic(self._state_path, self._state.model_dump())
            self._events_since_checkpoint = 0
            self._last_checkpoint_at = time.monotonic()

    def events_since(
        self, thread_id: str, since_seq: int | None = None
    ) -> list[RuntimeEventRecord]:
        path = self._events_path(thread_id)
        if not path.exists():
            return []
        out: list[RuntimeEventRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = RuntimeEventRecord.model_validate_json(line)
            except Exception:  # noqa: BLE001 — skip corrupt lines, keep the rest
                logger.warning(
                    "events_since_skip_corrupt_line thread_id=%s line=%.120s",
                    thread_id,
                    line,
                )
                continue
            if since_seq is not None and record.seq <= since_seq:
                continue
            out.append(record)
        return out

    async def current_seq(self) -> int:
        async with self._seq_lock:
            return self._state.next_seq - 1
