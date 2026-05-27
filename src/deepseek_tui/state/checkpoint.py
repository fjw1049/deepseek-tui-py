"""Crash-recovery checkpoints — mirrors ``session_manager.rs`` checkpoint APIs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import user_checkpoints_dir

CURRENT_SESSION_SCHEMA_VERSION = 1
CURRENT_QUEUE_SCHEMA_VERSION = 1


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


@dataclass(slots=True)
class OfflineQueueState:
    schema_version: int = CURRENT_QUEUE_SCHEMA_VERSION
    session_id: str | None = None
    queued_messages: list[str] = field(default_factory=list)
    draft: str | None = None


def checkpoint_path() -> Path:
    return user_checkpoints_dir() / "latest.json"


def offline_queue_path() -> Path:
    return user_checkpoints_dir() / "offline_queue.json"


def save_checkpoint(payload: dict[str, Any]) -> Path:
    data = {"schema_version": CURRENT_SESSION_SCHEMA_VERSION, **payload}
    path = checkpoint_path()
    _write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
    return path


def load_checkpoint() -> dict[str, Any] | None:
    path = checkpoint_path()
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = int(raw.get("schema_version", 0))
    if version > CURRENT_SESSION_SCHEMA_VERSION:
        raise ValueError(
            f"Checkpoint schema v{version} is newer than supported "
            f"v{CURRENT_SESSION_SCHEMA_VERSION}"
        )
    return raw


def clear_checkpoint() -> None:
    path = checkpoint_path()
    if path.is_file():
        path.unlink()


def save_offline_queue(
    state: OfflineQueueState,
    *,
    session_id: str | None = None,
) -> Path:
    state.session_id = session_id
    path = offline_queue_path()
    _write_atomic(
        path,
        json.dumps(
            {
                "schema_version": state.schema_version,
                "session_id": state.session_id,
                "queued_messages": state.queued_messages,
                "draft": state.draft,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return path


def load_offline_queue() -> OfflineQueueState | None:
    path = offline_queue_path()
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = int(raw.get("schema_version", 0))
    if version > CURRENT_QUEUE_SCHEMA_VERSION:
        raise ValueError(
            f"Offline queue schema v{version} is newer than supported "
            f"v{CURRENT_QUEUE_SCHEMA_VERSION}"
        )
    return OfflineQueueState(
        schema_version=version,
        session_id=raw.get("session_id"),
        queued_messages=list(raw.get("queued_messages") or []),
        draft=raw.get("draft"),
    )


def clear_offline_queue() -> None:
    path = offline_queue_path()
    if path.is_file():
        path.unlink()
