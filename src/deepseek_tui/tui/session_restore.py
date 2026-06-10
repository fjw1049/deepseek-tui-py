"""Shared TUI session JSON → Engine + Transcript restore helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.protocol.messages import Message

logger = logging.getLogger(__name__)


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
    engine.session_messages = list(messages)


def try_restore_crash_checkpoint(engine: Any) -> tuple[list[Message], dict[str, Any]] | None:
    """Restore engine state from ``latest.json`` if a crash checkpoint exists."""
    from deepseek_tui.state.checkpoint import load_checkpoint

    try:
        raw = load_checkpoint()
    except (OSError, ValueError) as exc:
        logger.warning("crash checkpoint load failed: %s", exc)
        return None
    if raw is None:
        return None

    messages_raw = raw.get("messages")
    if not isinstance(messages_raw, list) or not messages_raw:
        return None

    try:
        messages = [Message.model_validate(msg) for msg in messages_raw]
    except Exception:  # noqa: BLE001 — pydantic validation errors
        logger.warning("crash checkpoint messages invalid", exc_info=True)
        return None

    apply_messages_to_engine(engine, messages)

    metadata = raw.get("metadata")
    meta: dict[str, Any] = metadata if isinstance(metadata, dict) else {}

    turn_counter = raw.get("turn_counter")
    if isinstance(turn_counter, int) and turn_counter >= 0:
        engine.turn_counter = turn_counter

    model = raw.get("model")
    if isinstance(model, str) and model.strip():
        engine.default_model = model.strip()

    return messages, meta


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
