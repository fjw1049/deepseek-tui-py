"""Session catalog and import/export.
"""

from __future__ import annotations



# ======================================================================
# From session_catalog.py
# ======================================================================

"""Unified TUI session files + Workbench thread catalog."""


import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.server.threads import (
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


# ======================================================================
# From session_import.py
# ======================================================================

"""Import TUI session JSON snapshots into durable runtime threads."""


import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from deepseek_tui.server.threads import (
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
    tool_kind_for_name,
)
from deepseek_tui.config.paths import user_sessions_dir
from deepseek_tui.protocol.messages import (
    Message,
    Role,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from deepseek_tui.utils import summarize_text

SUMMARY_LIMIT = 280


class ImportTuiSessionRequest(BaseModel):
    """Import a TUI session file into a new Workbench thread."""

    session_id: str | None = None
    path: str | None = None
    workspace: str | None = None
    title: str | None = None
    model: str | None = None
    mode: str | None = None


def resolve_tui_session_path(
    *,
    session_id: str | None,
    path: str | None,
) -> Path:
    if path:
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"Session file not found: {candidate}")
        return candidate

    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id or path is required")

    sessions_dir = user_sessions_dir()
    for name in (f"{sid}.json", sid if sid.endswith(".json") else f"{sid}"):
        candidate = sessions_dir / name
        if candidate.is_file():
            return candidate
    if sid in ("current", "latest"):
        current = sessions_dir / "current.json"
        if current.is_file():
            return current
    raise FileNotFoundError(f"TUI session not found: {sid}")


def _message_text(message: Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            text = block.text.strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def import_messages_into_store(
    store: RuntimeThreadStore,
    *,
    thread_id: str,
    messages: list[Message],
) -> None:
    """Persist imported chat as completed turns + items."""
    now = datetime.now(timezone.utc)
    current_turn: TurnRecord | None = None
    open_tool_items: dict[str, str] = {}

    def finalize_turn() -> None:
        nonlocal current_turn
        if current_turn is None:
            return
        current_turn.status = RuntimeTurnStatus.COMPLETED
        current_turn.ended_at = now
        if current_turn.started_at:
            delta = now - current_turn.started_at
            current_turn.duration_ms = int(delta.total_seconds() * 1000)
        store.save_turn(current_turn)
        current_turn = None
        open_tool_items.clear()

    def append_item(item: TurnItemRecord) -> None:
        assert current_turn is not None
        current_turn.item_ids.append(item.id)
        store.save_item(item)
        store.save_turn(current_turn)

    for message in messages:
        if message.role == Role.USER:
            finalize_turn()
            turn_id = f"turn_{uuid.uuid4().hex[:8]}"
            text = _message_text(message)
            if not text:
                continue
            current_turn = TurnRecord(
                id=turn_id,
                thread_id=thread_id,
                status=RuntimeTurnStatus.IN_PROGRESS,
                input_summary=summarize_text(text, SUMMARY_LIMIT),
                created_at=now,
                started_at=now,
            )
            store.save_turn(current_turn)
            user_item = TurnItemRecord(
                id=f"item_{uuid.uuid4().hex[:8]}",
                turn_id=turn_id,
                kind=TurnItemKind.USER_MESSAGE,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=summarize_text(text, SUMMARY_LIMIT),
                detail=text,
                started_at=now,
                ended_at=now,
            )
            append_item(user_item)
        elif message.role == Role.ASSISTANT and current_turn is not None:
            text = _message_text(message)
            if text:
                append_item(
                    TurnItemRecord(
                        id=f"item_{uuid.uuid4().hex[:8]}",
                        turn_id=current_turn.id,
                        kind=TurnItemKind.AGENT_MESSAGE,
                        status=TurnItemLifecycleStatus.COMPLETED,
                        summary=summarize_text(text, SUMMARY_LIMIT),
                        detail=text,
                        started_at=now,
                        ended_at=now,
                    )
                )
            for block in message.content:
                if not isinstance(block, ToolUseBlock):
                    continue
                item_id = f"item_{uuid.uuid4().hex[:8]}"
                open_tool_items[block.id] = item_id
                append_item(
                    TurnItemRecord(
                        id=item_id,
                        turn_id=current_turn.id,
                        kind=tool_kind_for_name(block.name),
                        status=TurnItemLifecycleStatus.IN_PROGRESS,
                        summary=summarize_text(block.name, SUMMARY_LIMIT),
                        detail=json.dumps(block.input, default=str),
                        metadata={
                            "tool_use_id": block.id,
                            "tool_name": block.name,
                            "arguments": block.input,
                        },
                        started_at=now,
                    )
                )
        elif message.role == Role.TOOL and current_turn is not None:
            for block in message.content:
                if not isinstance(block, ToolResultBlock):
                    continue
                item_id = open_tool_items.get(block.tool_use_id)
                status = (
                    TurnItemLifecycleStatus.FAILED
                    if block.is_error
                    else TurnItemLifecycleStatus.COMPLETED
                )
                if item_id:
                    try:
                        item = store.load_item(item_id)
                    except FileNotFoundError:
                        item = None
                    if item is not None:
                        item.status = status
                        item.detail = block.content
                        item.ended_at = now
                        store.save_item(item)
                        continue
                append_item(
                    TurnItemRecord(
                        id=f"item_{uuid.uuid4().hex[:8]}",
                        turn_id=current_turn.id,
                        kind=TurnItemKind.TOOL_CALL,
                        status=status,
                        summary="tool_result",
                        detail=block.content,
                        metadata={"tool_use_id": block.tool_use_id},
                        started_at=now,
                        ended_at=now,
                    )
                )

    finalize_turn()


def load_tui_session_messages(path: Path) -> tuple[dict[str, Any], list[Message]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Session file must be a JSON object")
    messages_raw = raw.get("messages")
    if not isinstance(messages_raw, list):
        raise ValueError("Session file has no messages array")
    messages = [Message.model_validate(item) for item in messages_raw]
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return metadata, messages
