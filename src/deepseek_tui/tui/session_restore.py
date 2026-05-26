"""Shared TUI session JSON → Engine + Transcript restore helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.protocol.messages import Message


def parse_session_messages(session_data: dict[str, Any], *, path: Path | None = None) -> list[Message]:
    """Validate session JSON and return restored messages."""
    messages_raw = session_data.get("messages")
    if not isinstance(messages_raw, list):
        raise ValueError("session file has no messages")
    return [Message.model_validate(msg) for msg in messages_raw]


def session_metadata(
    session_data: dict[str, Any], *, path: Path | None = None
) -> dict[str, Any]:
    """Return metadata dict, synthesizing minimal fields when absent."""
    metadata = session_data.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    fallback_id = path.stem if path is not None else "session"
    return {"id": fallback_id, "message_count": len(session_data.get("messages") or [])}


def apply_messages_to_engine(engine: Any, messages: list[Message]) -> None:
    engine.session_messages.clear()
    engine.session_messages.extend(messages)


def session_started_at_iso(metadata: dict[str, Any], *, path: Path | None = None) -> str | None:
    """Best-effort ISO timestamp for filtering task sidebar rows after restore."""
    saved_at = metadata.get("saved_at")
    if isinstance(saved_at, str) and saved_at.strip():
        return saved_at.strip()
    exported_at = metadata.get("exported_at")
    if isinstance(exported_at, str) and exported_at.strip():
        return exported_at.strip()
    if path is not None:
        try:
            ts = path.stat().st_mtime
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except OSError:
            return None
    return None
