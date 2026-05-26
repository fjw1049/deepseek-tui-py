"""Unified TUI session files + Workbench thread catalog."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.app_server.runtime_threads import (
    RuntimeThreadStore,
    ThreadRecord,
    reconstruct_messages_from_turns,
)
from deepseek_tui.config.paths import user_sessions_dir
from deepseek_tui.protocol.messages import Message


def _title_from_metadata(metadata: dict[str, Any] | None, fallback: str) -> str:
    if metadata:
        title = metadata.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        session_id = metadata.get("id")
        if isinstance(session_id, str) and session_id.strip():
            return f"TUI {session_id.strip()[:8]}"
    return fallback


def scan_tui_session_files(*, limit: int = 50) -> list[dict[str, Any]]:
    """List importable TUI session JSON files under ``~/.deepseek/sessions``."""
    sessions_dir = user_sessions_dir()
    if not sessions_dir.is_dir():
        return []

    rows: list[dict[str, Any]] = []
    for path in sorted(
        sessions_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        messages = raw.get("messages")
        if not isinstance(messages, list) or not messages:
            continue
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        session_id = (
            str(metadata.get("id")).strip()
            if isinstance(metadata.get("id"), str) and str(metadata.get("id")).strip()
            else path.stem
        )
        stat = path.stat()
        rows.append(
            {
                "kind": "tui",
                "session_id": session_id,
                "path": str(path.resolve()),
                "title": _title_from_metadata(metadata, path.stem),
                "model": metadata.get("model") if isinstance(metadata.get("model"), str) else None,
                "workspace": (
                    metadata.get("workspace")
                    if isinstance(metadata.get("workspace"), str)
                    else None
                ),
                "message_count": len(messages),
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "workbench_thread_id": (
                    metadata.get("workbench_thread_id")
                    if isinstance(metadata.get("workbench_thread_id"), str)
                    else None
                ),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def list_unified_sessions(
    store: RuntimeThreadStore,
    threads: list[ThreadRecord],
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Merge TUI session files with Workbench threads for a single picker surface."""
    thread_by_session_id = {
        t.source_session_id: t
        for t in threads
        if t.source_session_id
    }
    thread_by_session_path = {
        t.source_session_path: t
        for t in threads
        if t.source_session_path
    }
    thread_by_id = {t.id: t for t in threads}

    entries: list[dict[str, Any]] = []
    seen_thread_ids: set[str] = set()

    for tui in scan_tui_session_files(limit=limit):
        linked = None
        wb_id = tui.get("workbench_thread_id")
        if isinstance(wb_id, str) and wb_id in thread_by_id:
            linked = thread_by_id[wb_id]
        if linked is None:
            linked = thread_by_session_id.get(tui["session_id"]) or thread_by_session_path.get(
                tui["path"]
            )
        if linked is not None:
            seen_thread_ids.add(linked.id)
            tui = {
                **tui,
                "linked_thread_id": linked.id,
                "import_state": "linked",
            }
        else:
            tui = {**tui, "linked_thread_id": None, "import_state": "available"}
        entries.append(tui)

    for thread in threads:
        if thread.archived or thread.id in seen_thread_ids:
            continue
        entries.append(
            {
                "kind": "thread",
                "thread_id": thread.id,
                "title": thread.title or thread.id[:8],
                "model": thread.model,
                "workspace": thread.workspace,
                "modified_at": thread.updated_at.isoformat(),
                "source_session_id": thread.source_session_id,
                "source_session_path": thread.source_session_path,
                "import_state": "native",
            }
        )

    entries.sort(key=lambda row: row.get("modified_at") or "", reverse=True)
    return entries[:limit]


def export_thread_to_tui_session(
    store: RuntimeThreadStore,
    thread: ThreadRecord,
    *,
    session_id: str | None = None,
) -> tuple[Path, str]:
    """Write a Workbench thread back to a TUI-compatible session JSON file."""
    messages: list[Message] = reconstruct_messages_from_turns(store, thread.id)
    if not messages:
        raise ValueError("thread has no exportable messages")

    sid = (session_id or thread.source_session_id or thread.id).strip()
    if not sid:
        sid = thread.id

    sessions_dir = user_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{sid}.json"

    payload = {
        "metadata": {
            "id": sid,
            "title": thread.title or f"Workbench {thread.id[:8]}",
            "model": thread.model,
            "workspace": thread.workspace,
            "workbench_thread_id": thread.id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "model": thread.model,
        "messages": [message.model_dump(mode="json") for message in messages],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path, sid
