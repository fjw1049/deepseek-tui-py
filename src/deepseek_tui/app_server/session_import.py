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
