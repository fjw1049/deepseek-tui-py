"""File-based persistence for threads/turns/items (JSON) and events (JSONL).

Pure I/O — no engine logic lives here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

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


class _VersionedRecord(Protocol):
    schema_version: int

    @classmethod
    def model_validate(cls, obj: Any) -> Any: ...


_T = TypeVar("_T", bound=_VersionedRecord)


def validate_record_id(value: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or any(
        char in value for char in "/\\\0:"
    ):
        raise ValueError("Invalid record ID")
    return value


_F = TypeVar("_F", bound=Callable[..., Any])


def _serialized(method: _F) -> _F:
    @wraps(method)
    def guarded(self: RuntimeThreadStore, *args: Any, **kwargs: Any) -> Any:
        with self.event_lock():
            return method(self, *args, **kwargs)
    return cast(_F, guarded)


class RuntimeThreadStore:
    """File-based store: threads/turns/items as individual JSON, events as JSONL."""

    def __init__(self, root: Path) -> None:
        self._lock_state = threading.local()
        self._root = root
        self._threads_dir = root / "threads"
        self._turns_dir = root / "turns"
        self._items_dir = root / "items"
        self._events_dir = root / "events"
        self._worktree_baselines_dir = root / "worktree_baselines"
        self._rewind_audit_dir = root / "rewind_audit"
        self._state_path = root / "state.json"

        for d in (
            self._threads_dir,
            self._turns_dir,
            self._items_dir,
            self._events_dir,
            self._worktree_baselines_dir,
            self._rewind_audit_dir,
        ):
            if d.is_symlink():
                raise ValueError(f"Symlink store directory: {d}")
            d.mkdir(parents=True, exist_ok=True)

        self._event_write_locks: dict[str, asyncio.Lock] = {}
        # The lock lives outside the replaceable store tree.
        with self.event_lock():
            self._state = self._read_state()
            # Recover the high-water mark written by older batched-checkpoint stores.
            for path in self._events_dir.glob("*.jsonl"):
                for record in self.iter_events(path.stem):
                    self._state.next_seq = max(self._state.next_seq, record.seq + 1)
            write_json_atomic(self._state_path, self._state.model_dump())

    @property
    def root(self) -> Path:
        return self._root

    @contextmanager
    def event_lock(self) -> Iterator[None]:
        from deepseek_tui.workspace.project_lease import FileLease

        if getattr(self._lock_state, "held", False):
            yield
            return
        lease = FileLease(self._root.parent / f".{self._root.name}.events.lock")
        lease.acquire_blocking()
        self._lock_state.held = True
        try:
            yield
        finally:
            self._lock_state.held = False
            lease.release()

    @_serialized
    def _read_state(self) -> RuntimeStoreState:
        if not self._state_path.exists():
            return RuntimeStoreState()
        return RuntimeStoreState.model_validate_json(self._state_path.read_text(encoding="utf-8"))

    # --- paths ---------------------------------------------------------------

    def _record_path(self, directory: Path, record_id: str, suffix: str) -> Path:
        path = directory / f"{validate_record_id(record_id)}.{suffix}"
        if directory.is_symlink() or path.is_symlink():
            raise ValueError("Symlink store path")
        return path


    def _thread_path(self, thread_id: str) -> Path:
        return self._record_path(self._threads_dir, thread_id, "json")

    def _turn_path(self, turn_id: str) -> Path:
        return self._record_path(self._turns_dir, turn_id, "json")

    def _item_path(self, item_id: str) -> Path:
        return self._record_path(self._items_dir, item_id, "json")

    def _events_path(self, thread_id: str) -> Path:
        return self._record_path(self._events_dir, thread_id, "jsonl")

    def _worktree_baseline_path(self, thread_id: str) -> Path:
        return self._record_path(self._worktree_baselines_dir, thread_id, "json")

    def _rewind_audit_path(self, thread_id: str) -> Path:
        return self._record_path(self._rewind_audit_dir, thread_id, "jsonl")

    # --- CRUD ----------------------------------------------------------------

    @_serialized
    def save_thread(self, thread: ThreadRecord) -> None:
        if thread.latest_turn_id is not None:
            validate_record_id(thread.latest_turn_id)
        write_json_atomic(self._thread_path(thread.id), thread.model_dump(mode="json"))

    @_serialized
    def save_turn(self, turn: TurnRecord) -> None:
        validate_record_id(turn.thread_id)
        for item_id in turn.item_ids:
            validate_record_id(item_id)
        write_json_atomic(self._turn_path(turn.id), turn.model_dump(mode="json"))

    @_serialized
    def save_item(self, item: TurnItemRecord) -> None:
        validate_record_id(item.turn_id)
        write_json_atomic(self._item_path(item.id), item.model_dump(mode="json"))

    @_serialized
    def delete_turn(self, turn_id: str) -> None:
        self._turn_path(turn_id).unlink(missing_ok=True)

    @_serialized
    def delete_item(self, item_id: str) -> None:
        self._item_path(item_id).unlink(missing_ok=True)

    @_serialized
    def delete_thread(self, thread_id: str) -> None:
        self._thread_path(thread_id).unlink(missing_ok=True)
        self.delete_worktree_baseline(thread_id)
        self.delete_rewind_audit(thread_id)

    @_serialized
    def delete_events(self, thread_id: str) -> None:
        self._events_path(thread_id).unlink(missing_ok=True)

    @_serialized
    def save_worktree_baseline(self, thread_id: str, baseline: dict[str, Any]) -> None:
        write_json_atomic(self._worktree_baseline_path(thread_id), baseline)

    @_serialized
    def load_worktree_baseline(self, thread_id: str) -> dict[str, Any] | None:
        path = self._worktree_baseline_path(thread_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("invalid_worktree_baseline thread=%s", thread_id)
            return None
        return raw if isinstance(raw, dict) else None

    @_serialized
    def delete_worktree_baseline(self, thread_id: str) -> None:
        self._worktree_baseline_path(thread_id).unlink(missing_ok=True)

    # --- rewind audit (JSONL append) -----------------------------------------

    @_serialized
    def append_rewind_audit(self, thread_id: str, record: dict[str, Any]) -> None:
        """Durably append one rewind audit record before any deletion happens.

        A crash after the append leaves a harmless archive of turns that are
        still on disk; deleting first would make the rewind unrecoverable.
        """
        path = self._rewind_audit_path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

    @_serialized
    def list_rewind_audit(self, thread_id: str) -> list[dict[str, Any]]:
        path = self._rewind_audit_path(thread_id)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(
                    "rewind_audit_skip_corrupt_line thread_id=%s", thread_id
                )
                continue
            if isinstance(record, dict):
                out.append(record)
        return out

    @_serialized
    def delete_rewind_audit(self, thread_id: str) -> None:
        self._rewind_audit_path(thread_id).unlink(missing_ok=True)

    @_serialized
    def iter_turns(self) -> list[TurnRecord]:
        out: list[TurnRecord] = []
        if not self._turns_dir.exists():
            return out
        for path in self._turns_dir.glob("*.json"):
            record = self._load_listing_record(path, TurnRecord)
            if record is not None:
                out.append(record)
        return out

    @_serialized
    def iter_items(self) -> list[TurnItemRecord]:
        out: list[TurnItemRecord] = []
        if not self._items_dir.exists():
            return out
        for path in self._items_dir.glob("*.json"):
            record = self._load_listing_record(path, TurnItemRecord)
            if record is not None:
                out.append(record)
        return out

    def compact_events(self, thread_id: str, *, drop_noisy: bool = True) -> int:
        with self.event_lock():
            return self._compact_events(thread_id, drop_noisy=drop_noisy)

    def _compact_events(self, thread_id: str, *, drop_noisy: bool = True) -> int:
        """Rewrite a thread's event log, dropping noisy delta events.

        Returns the number of events removed. Conversation items are untouched.
        """
        from deepseek_tui.server.data_inventory import is_noisy_event_name

        path = self._events_path(thread_id)
        if not path.exists():
            return 0
        kept: list[RuntimeEventRecord] = []
        removed = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = RuntimeEventRecord.model_validate_json(line)
            except Exception:  # noqa: BLE001
                removed += 1
                continue
            if drop_noisy and is_noisy_event_name(record.event):
                removed += 1
                continue
            kept.append(record)
        if removed == 0:
            return 0
        if not kept:
            path.unlink(missing_ok=True)
            return removed
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for record in kept:
                f.write(record.model_dump_json() + "\n")
        tmp.replace(path)
        return removed

    @_serialized
    def load_thread(self, thread_id: str) -> ThreadRecord:
        path = self._thread_path(thread_id)
        if not path.exists():
            raise FileNotFoundError(f"Thread not found: {thread_id}")
        if path.is_symlink():
            raise ValueError(f"Symlink record: {path.name}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("id") != path.stem:
            raise ValueError(f"Record ID does not match filename: {path.name}")
        record = ThreadRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Thread schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    @_serialized
    def load_turn(self, turn_id: str) -> TurnRecord:
        path = self._turn_path(turn_id)
        if not path.exists():
            raise FileNotFoundError(f"Turn not found: {turn_id}")
        if path.is_symlink():
            raise ValueError(f"Symlink record: {path.name}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("id") != path.stem:
            raise ValueError(f"Record ID does not match filename: {path.name}")
        record = TurnRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Turn schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    @_serialized
    def load_item(self, item_id: str) -> TurnItemRecord:
        path = self._item_path(item_id)
        if not path.exists():
            raise FileNotFoundError(f"Item not found: {item_id}")
        if path.is_symlink():
            raise ValueError(f"Symlink record: {path.name}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("id") != path.stem:
            raise ValueError(f"Record ID does not match filename: {path.name}")
        record = TurnItemRecord.model_validate(raw)
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            raise ValueError(
                f"Item schema v{record.schema_version} is newer than supported "
                f"v{CURRENT_RUNTIME_SCHEMA_VERSION}"
            )
        return record

    def _load_listing_record(self, path: Path, model: type[_T]) -> _T | None:
        """Load one record during a directory listing.

        A single corrupt/unreadable/newer-schema file must not take down the
        whole listing (and with it server startup recovery) — skip it and warn.
        """
        try:
            if path.is_symlink():
                raise ValueError("Symlink record")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("id") != path.stem:
                raise ValueError("Record ID does not match filename")
            validate_record_id(path.stem)
            record: _T = model.model_validate(raw)
        except Exception:
            logger.warning("Skipping unreadable record file: %s", path, exc_info=True)
            return None
        if record.schema_version > CURRENT_RUNTIME_SCHEMA_VERSION:
            logger.warning(
                "Skipping %s: schema v%s is newer than supported v%s",
                path,
                record.schema_version,
                CURRENT_RUNTIME_SCHEMA_VERSION,
            )
            return None
        return record

    @_serialized
    def list_threads(self) -> list[ThreadRecord]:
        out: list[ThreadRecord] = []
        if not self._threads_dir.exists():
            return out
        for path in self._threads_dir.glob("*.json"):
            record = self._load_listing_record(path, ThreadRecord)
            if record is not None:
                out.append(record)
        out.sort(key=lambda t: t.updated_at, reverse=True)
        return out

    @_serialized
    def count_turns_by_thread(self) -> dict[str, int]:
        """Aggregate sidebar counts in one scan rather than one scan per thread."""
        counts: dict[str, int] = {}
        for path in self._turns_dir.glob("*.json"):
            record = self._load_listing_record(path, TurnRecord)
            if record is not None:
                counts[record.thread_id] = counts.get(record.thread_id, 0) + 1
        return counts

    @_serialized
    def list_turns_for_thread(self, thread_id: str) -> list[TurnRecord]:
        out: list[TurnRecord] = []
        if not self._turns_dir.exists():
            return out
        for path in self._turns_dir.glob("*.json"):
            record = self._load_listing_record(path, TurnRecord)
            if record is not None and record.thread_id == thread_id:
                out.append(record)
        out.sort(key=lambda t: t.created_at)
        return out

    @_serialized
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
            record = self._load_listing_record(path, TurnItemRecord)
            if record is not None and record.turn_id == turn_id:
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

        from deepseek_tui.server.lifecycle import complete_before_cancel

        validate_record_id(thread_id)
        for related_id in (turn_id, item_id):
            if related_id is not None:
                validate_record_id(related_id)
        lock = self._event_write_locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            return await complete_before_cancel(asyncio.to_thread(
                self._append_event, thread_id, turn_id, item_id, event, payload
            ))

    def _append_event(
        self, thread_id: str, turn_id: str | None, item_id: str | None,
        event: str, payload: dict[str, Any],
    ) -> RuntimeEventRecord:
        with self.event_lock():
            state = self._read_state()
            seq = state.next_seq
            state.next_seq += 1
            # Reserve durably before appending: failures may leave gaps, never reuse IDs.
            write_json_atomic(self._state_path, state.model_dump())
            self._state = state
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
            # Separate a crash-torn final line so it cannot swallow the next record.
            if path.exists() and path.stat().st_size:
                with path.open("rb+") as stream:
                    stream.seek(-1, os.SEEK_END)
                    if stream.read(1) != b"\n":
                        stream.write(b"\n")
            with path.open("a", encoding="utf-8") as stream:
                stream.write(record.model_dump_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return record

    async def flush_event_checkpoint(self) -> None:
        """Every append now persists its reservation before writing the event."""

    def iter_events(
        self, thread_id: str, since_seq: int | None = None
    ) -> Iterator[RuntimeEventRecord]:
        path = self._events_path(thread_id)
        if not path.exists():
            return
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    record = RuntimeEventRecord.model_validate_json(line)
                except Exception:
                    logger.warning("events_since_skip_corrupt_line thread_id=%s", thread_id)
                    continue
                if record.thread_id == thread_id and (since_seq is None or record.seq > since_seq):
                    yield record

    def event_pages(
        self, thread_id: str, since_seq: int | None = None, *, page_size: int = 256
    ) -> Iterator[list[RuntimeEventRecord]]:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        page = []
        for record in self.iter_events(thread_id, since_seq):
            page.append(record)
            if len(page) == page_size:
                yield page
                page = []
        if page:
            yield page

    def events_since(
        self, thread_id: str, since_seq: int | None = None
    ) -> list[RuntimeEventRecord]:
        return list(self.iter_events(thread_id, since_seq))

    async def current_seq(self) -> int:
        import asyncio
        return await asyncio.to_thread(lambda: self._read_state().next_seq - 1)
