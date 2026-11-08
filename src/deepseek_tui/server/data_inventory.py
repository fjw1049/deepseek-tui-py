"""Local data inventory and maintenance for Workbench Settings.

Inventory reports what lives under ``~/.deepseek`` (``threads/`` is the
conversation source of truth; ``sessions/`` and any ``state.db`` are legacy).
Maintenance ops reclaim disk without touching Skills, MCP, plugins, or
config — matching the product safety gradient:

* optimize — never deletes user-visible conversations
* clean-by-age — deletes whole old threads
* clear-history — deletes all conversations; keeps identity/capability data
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.browser import ARTIFACTS_DIRNAME
from deepseek_tui.config.paths import (
    user_browser_dir,
    user_deepseek_dir,
    user_logs_dir,
    user_media_dir,
    user_sessions_dir,
    user_state_db_path,
    user_thread_plan_path,
    user_threads_dir,
    user_worktrees_dir,
)
from deepseek_tui.server.threads.models import TurnItemKind
from deepseek_tui.server.threads.store import RuntimeThreadStore
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpointStore

logger = logging.getLogger(__name__)

# High-noise SSE events: safe to drop after a turn completes (items remain).
_NOISY_EVENT_NAMES = frozenset(
    {
        "response.delta",
        "item.delta",
        "turn.delta",
        "agent.message.delta",
        "agent.reasoning.delta",
    }
)
_NOISY_EVENT_SUFFIX = ".delta"
# Write-time cap for noisy event payloads (chars of JSON).
EVENT_DELTA_PAYLOAD_MAX_CHARS = 2048
DEFAULT_CHECKPOINT_MAX_AGE_DAYS = 7
CYCLE_ARCHIVE_MAX_AGE_DAYS = 30
CRASH_CHECKPOINT_MAX_AGE_SECS = 7 * 86400
# Writers save an item before the turn that lists it (and a turn before its
# thread). Optimize runs without thread leases, so only records older than
# this are treated as orphans; a live turn never loses its newest item.
ORPHAN_GRACE_SECS = 600
_MESSAGE_KINDS = frozenset(
    {
        TurnItemKind.USER_MESSAGE,
        TurnItemKind.AGENT_MESSAGE,
    }
)


def directory_size(path: Path) -> int:
    """Total byte size of ``path`` (file or directory tree)."""
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def _tree_bytes(path: Path) -> int:
    """Fast size of a file or tree; never follows symlinks (browser profiles use them)."""
    try:
        if path.is_symlink() or not path.is_dir():
            return path.lstat().st_size
    except OSError:
        return 0
    total = 0
    stack = [path]
    while stack:
        try:
            entries = os.scandir(stack.pop())
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    else:
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    return total


def storage_categories(
    *, home: Path, threads_root: Path, sessions_root: Path, state_db: Path,
    logs_dir: Path | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Split the whole data home into the groups Settings explains.

    Everything not named lands in ``other`` so the parts always add up to the total.
    """
    groups: dict[str, list[Path]] = {
        "conversations": [threads_root, sessions_root, state_db, user_media_dir()],
        "browser": [user_browser_dir(home)],
        "workspace": [home / "workspace"],
        "logs": [logs_dir or user_logs_dir()],
        "worktrees": [user_worktrees_dir()],
    }
    top: dict[str, int] = {}
    try:
        with os.scandir(home) as entries:
            for entry in entries:
                top[entry.name] = _tree_bytes(Path(entry.path))
    except OSError:
        pass
    # Partition overlapping roots instead of counting a nested custom thread
    # directory once as workspace data and again as conversation data.
    home = home.absolute()
    owners: dict[Path, str] = {}
    for key, paths in groups.items():
        for path in paths:
            owners.setdefault(path.absolute(), key)
    owners.setdefault(home, "other")
    sizes = {
        path: sum(top.values()) if path == home else (
            top.get(path.name, 0) if path.parent == home else _tree_bytes(path)
        )
        for path in owners
    }
    totals = dict.fromkeys([*groups, "other"], 0)
    for path, key in owners.items():
        children = [child for child in owners if child != path and child.is_relative_to(path)]
        direct = [child for child in children if not any(
            child != parent and child.is_relative_to(parent) for parent in children
        )]
        totals[key] += max(0, sizes[path] - sum(sizes[child] for child in direct))
    categories: list[dict[str, Any]] = []
    for key, size in totals.items():
        reveal_dir = home if key == "other" else (
            threads_root if key == "conversations" else groups[key][0]
        )
        categories.append({
            "key": key, "bytes": size,
            "reveal_path": str(reveal_dir) if reveal_dir.is_dir() else None,
        })
    return sum(totals.values()), categories


def is_noisy_event_name(event: str) -> bool:
    name = (event or "").strip()
    if not name:
        return False
    if name in _NOISY_EVENT_NAMES:
        return True
    return name.endswith(_NOISY_EVENT_SUFFIX)


def truncate_event_payload(payload: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    """Shrink a noisy event payload for write-time limits."""
    try:
        raw = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"_truncated": True, "_reason": "unserializable"}
    if len(raw) <= max_chars:
        return payload
    return {
        "_truncated": True,
        "_original_chars": len(raw),
        "preview": raw[: max(0, max_chars - 64)],
    }


def collect_inventory(
    *,
    threads_dir: Path | None = None,
    sessions_dir: Path | None = None,
    state_db_path: Path | None = None,
    home_dir: Path | None = None,
    logs_dir: Path | None = None,
) -> dict[str, Any]:
    """Return path + size + count summary for Settings cards."""
    threads_root = threads_dir or user_threads_dir()
    sessions_root = sessions_dir or user_sessions_dir()
    state_db = state_db_path or user_state_db_path()
    home = home_dir or user_deepseek_dir()

    store = RuntimeThreadStore(threads_root)
    threads = store.list_threads()
    thread_count = len(threads)
    message_count = 0
    item_count = 0
    for thread in threads:
        for turn in store.list_turns_for_thread(thread.id):
            for item in store.list_items_for_turn(turn.id):
                item_count += 1
                if item.kind in _MESSAGE_KINDS:
                    message_count += 1

    events_bytes = directory_size(threads_root / "events")
    checkpoints_bytes = directory_size(threads_root / "checkpoints")
    threads_bytes = directory_size(threads_root)
    sessions_bytes = directory_size(sessions_root)
    state_db_bytes = directory_size(state_db)
    storage_total, categories = storage_categories(
        home=home, threads_root=threads_root, sessions_root=sessions_root, state_db=state_db,
        logs_dir=logs_dir,
    )

    return {
        "home_dir": str(home),
        "threads_dir": str(threads_root),
        "sessions_dir": str(sessions_root),
        "conversation_source_of_truth": "threads",
        "state_db_path": str(state_db),
        "threads_bytes": threads_bytes,
        "sessions_bytes": sessions_bytes,
        "state_db_bytes": state_db_bytes,
        "events_bytes": events_bytes,
        "checkpoints_bytes": checkpoints_bytes,
        "thread_count": thread_count,
        "message_count": message_count,
        "item_count": item_count,
        "total_bytes": threads_bytes + sessions_bytes + state_db_bytes,
        "storage_total_bytes": storage_total,
        "categories": categories,
        "workspace_dir": str(home / "workspace"),
    }


@dataclass(slots=True)
class OptimizeReport:
    bytes_before: int = 0
    bytes_after: int = 0
    bytes_reclaimed: int = 0
    events_stripped: int = 0
    orphan_turns_removed: int = 0
    orphan_items_removed: int = 0
    checkpoints_pruned: int = 0
    cycle_archives_pruned: int = 0
    crash_checkpoints_cleared: int = 0
    tool_outputs_pruned: int = 0
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "bytes_reclaimed": self.bytes_reclaimed,
            "events_stripped": self.events_stripped,
            "orphan_turns_removed": self.orphan_turns_removed,
            "orphan_items_removed": self.orphan_items_removed,
            "checkpoints_pruned": self.checkpoints_pruned,
            "cycle_archives_pruned": self.cycle_archives_pruned,
            "crash_checkpoints_cleared": self.crash_checkpoints_cleared,
            "tool_outputs_pruned": self.tool_outputs_pruned,
            "details": list(self.details),
        }


@dataclass(slots=True)
class CleanReport:
    threads_deleted: int = 0
    threads_skipped: int = 0
    bytes_reclaimed: int = 0
    thread_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "threads_deleted": self.threads_deleted,
            "threads_skipped": self.threads_skipped,
            "bytes_reclaimed": self.bytes_reclaimed,
            "thread_ids": list(self.thread_ids),
        }


@dataclass(slots=True)
class ClearHistoryReport:
    threads_deleted: int = 0
    sessions_cleared: int = 0
    bytes_reclaimed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "threads_deleted": self.threads_deleted,
            "sessions_cleared": self.sessions_cleared,
            "bytes_reclaimed": self.bytes_reclaimed,
            "preserved": ["config", "skills", "mcp", "plugins", "secrets", "automations"],
        }


def delete_thread_tree(
    store: RuntimeThreadStore,
    checkpoints: TurnCheckpointStore,
    thread_id: str,
) -> int:
    """Delete one thread and all turns/items/events/checkpoints. Returns bytes removed."""
    before = directory_size(store.root)
    for turn in store.list_turns_for_thread(thread_id):
        for item_id in list(turn.item_ids):
            store.delete_item(item_id)
        # Also sweep any items that still claim this turn_id.
        for item in store.list_items_for_turn(turn.id):
            store.delete_item(item.id)
        store.delete_turn(turn.id)
        checkpoints.delete(turn.id)
    for cp in checkpoints.list_for_thread(thread_id):
        checkpoints.delete(cp.turn_id)
    store.delete_events(thread_id)
    store.delete_thread(thread_id)
    # Browser evidence, downloads and saved logins belong to the deleted conversation.
    if Path(thread_id).name == thread_id:
        shutil.rmtree(store.root / ARTIFACTS_DIRNAME / thread_id, ignore_errors=True)
        shutil.rmtree(user_browser_dir(store.root.parent) / "profiles" / thread_id, ignore_errors=True)
    try:
        plan_path = user_thread_plan_path(thread_id)
        if plan_path.is_file():
            plan_path.unlink()
    except (ValueError, OSError):
        logger.debug("delete_thread_plan_failed thread=%s", thread_id, exc_info=True)
    after = directory_size(store.root)
    return max(0, before - after)


def optimize_storage(
    store: RuntimeThreadStore,
    checkpoints: TurnCheckpointStore,
    *,
    max_checkpoint_age_days: int = DEFAULT_CHECKPOINT_MAX_AGE_DAYS,
    sessions_dir: Path | None = None,
) -> OptimizeReport:
    """Reclaim redundant disk without deleting conversations."""
    sessions_root = sessions_dir or user_sessions_dir()
    report = OptimizeReport()
    report.bytes_before = directory_size(store.root) + directory_size(sessions_root)

    # 1) Strip noisy delta events from every thread event log.
    for thread in store.list_threads():
        stripped = store.compact_events(thread.id, drop_noisy=True)
        report.events_stripped += stripped

    # 2) Orphan turns/items (not referenced by any remaining thread).
    live_thread_ids = {t.id for t in store.list_threads()}
    live_turn_ids: set[str] = set()
    live_item_ids: set[str] = set()
    for thread_id in live_thread_ids:
        for turn in store.list_turns_for_thread(thread_id):
            live_turn_ids.add(turn.id)
            live_item_ids.update(turn.item_ids)

    for turn in store.iter_turns():
        if turn.thread_id not in live_thread_ids or turn.id not in live_turn_ids:
            if _recently_written(store.root / "turns" / f"{turn.id}.json"):
                continue
            store.delete_turn(turn.id)
            checkpoints.delete(turn.id)
            report.orphan_turns_removed += 1

    for item in store.iter_items():
        if item.id not in live_item_ids:
            if _recently_written(store.root / "items" / f"{item.id}.json"):
                continue
            store.delete_item(item.id)
            report.orphan_items_removed += 1

    # 3) Checkpoint TTL.
    protected_checkpoint_ids = set(live_turn_ids)
    protected_checkpoint_ids.update(
        cp.turn_id
        for thread_id in live_thread_ids
        for cp in checkpoints.list_for_thread(thread_id)
    )
    report.checkpoints_pruned = checkpoints.prune_older_than(
        max_checkpoint_age_days,
        protected_turn_ids=protected_checkpoint_ids,
    )

    # 4) Session-side redundancy (cycles / stale crash checkpoints).
    report.cycle_archives_pruned = _prune_cycle_archives(
        sessions_root, max_age_days=CYCLE_ARCHIVE_MAX_AGE_DAYS
    )
    report.crash_checkpoints_cleared = _prune_stale_crash_checkpoint(sessions_root)

    # 5) Tool output spillover (existing helper).
    try:
        from deepseek_tui.tools.runtime import prune_older_than

        report.tool_outputs_pruned = prune_older_than()
    except Exception:  # noqa: BLE001 — best-effort
        logger.debug("tool_outputs prune skipped", exc_info=True)

    report.bytes_after = directory_size(store.root) + directory_size(sessions_root)
    report.bytes_reclaimed = max(0, report.bytes_before - report.bytes_after)
    if report.bytes_reclaimed == 0 and report.events_stripped:
        report.details.append("events compacted; size change may be small after JSON rewrite")
    return report


def clear_conversation_history(
    store: RuntimeThreadStore,
    checkpoints: TurnCheckpointStore,
    *,
    sessions_dir: Path | None = None,
    clear_sessions: bool = True,
) -> ClearHistoryReport:
    """Delete all conversations; leave config/skills/mcp/plugins alone."""
    sessions_root = sessions_dir or user_sessions_dir()
    before = directory_size(store.root) + directory_size(sessions_root)
    report = ClearHistoryReport()
    for thread in list(store.list_threads()):
        delete_thread_tree(store, checkpoints, thread.id)
        report.threads_deleted += 1

    # Sweep any leftover orphan files under the store root.
    for turn in list(store.iter_turns()):
        store.delete_turn(turn.id)
        checkpoints.delete(turn.id)
    for item in list(store.iter_items()):
        store.delete_item(item.id)
    for path in (store.root / "events").glob("*.jsonl"):
        path.unlink(missing_ok=True)
    for path in (store.root / "transcripts").glob("*.jsonl"):
        path.unlink(missing_ok=True)
    for path in (store.root / "checkpoints").glob("*.json"):
        path.unlink(missing_ok=True)

    if clear_sessions:
        report.sessions_cleared = _clear_session_conversation_files(sessions_root)

    after = directory_size(store.root) + directory_size(sessions_root)
    report.bytes_reclaimed = max(0, before - after)
    return report


def _recently_written(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime < ORPHAN_GRACE_SECS
    except OSError:
        return False


def _prune_cycle_archives(sessions_root: Path, *, max_age_days: int) -> int:
    if not sessions_root.exists() or max_age_days < 1:
        return 0
    cutoff = time.time() - (max_age_days * 86400)
    removed = 0
    for path in sessions_root.glob("*/cycles/*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


def _prune_stale_crash_checkpoint(sessions_root: Path) -> int:
    latest = sessions_root / "checkpoints" / "latest.json"
    if not latest.is_file():
        return 0
    try:
        age = time.time() - latest.stat().st_mtime
    except OSError:
        return 0
    if age < CRASH_CHECKPOINT_MAX_AGE_SECS:
        return 0
    latest.unlink(missing_ok=True)
    return 1


def _clear_session_conversation_files(sessions_root: Path) -> int:
    """Remove TUI session JSON / archives / cycles; keep directory structure."""
    if not sessions_root.exists():
        return 0
    cleared = 0
    for path in list(sessions_root.glob("*.json")):
        path.unlink(missing_ok=True)
        cleared += 1
    archived = sessions_root / "archived"
    if archived.is_dir():
        for path in list(archived.glob("*.json")):
            path.unlink(missing_ok=True)
            cleared += 1
    for cycle_dir in sessions_root.glob("*/cycles"):
        if cycle_dir.is_dir():
            shutil.rmtree(cycle_dir, ignore_errors=True)
            cleared += 1
    for path in (
        sessions_root / "checkpoints" / "latest.json",
        sessions_root / "checkpoints" / "offline_queue.json",
    ):
        if path.is_file():
            path.unlink(missing_ok=True)
            cleared += 1
    return cleared


__all__ = [
    "EVENT_DELTA_PAYLOAD_MAX_CHARS",
    "DEFAULT_CHECKPOINT_MAX_AGE_DAYS",
    "OptimizeReport",
    "CleanReport",
    "ClearHistoryReport",
    "collect_inventory",
    "clear_conversation_history",
    "delete_thread_tree",
    "directory_size",
    "is_noisy_event_name",
    "optimize_storage",
    "truncate_event_payload",
]
