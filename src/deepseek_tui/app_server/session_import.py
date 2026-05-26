"""Import TUI session JSON snapshots into durable runtime threads."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from deepseek_tui.app_server.runtime_threads import (
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
)
from deepseek_tui.config.paths import user_sessions_dir
from deepseek_tui.protocol.messages import Message, Role, TextBlock
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
    """Persist imported chat as completed turns + items (user/assistant only)."""
    now = datetime.now(timezone.utc)
    current_turn: TurnRecord | None = None

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
            current_turn.item_ids.append(user_item.id)
            store.save_item(user_item)
            store.save_turn(current_turn)
        elif message.role == Role.ASSISTANT and current_turn is not None:
            text = _message_text(message)
            if not text:
                continue
            item = TurnItemRecord(
                id=f"item_{uuid.uuid4().hex[:8]}",
                turn_id=current_turn.id,
                kind=TurnItemKind.AGENT_MESSAGE,
                status=TurnItemLifecycleStatus.COMPLETED,
                summary=summarize_text(text, SUMMARY_LIMIT),
                detail=text,
                started_at=now,
                ended_at=now,
            )
            current_turn.item_ids.append(item.id)
            store.save_item(item)
            store.save_turn(current_turn)

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
