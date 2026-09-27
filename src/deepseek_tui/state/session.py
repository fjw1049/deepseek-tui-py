"""Workspace/session-scoped crash checkpoints, with legacy latest.json reads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import user_checkpoints_dir
from deepseek_tui.utils import write_text_atomic

CURRENT_SESSION_SCHEMA_VERSION = 1
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024


def checkpoint_path(*, workspace: Path | None = None, session_id: str | None = None) -> Path:
    root = user_checkpoints_dir()
    if workspace is None:
        return root / "latest.json"
    root /= hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()
    name = hashlib.sha256(session_id.encode()).hexdigest() if session_id else "latest"
    return root / f"{name}.json"


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        data = stream.read(MAX_CHECKPOINT_BYTES + 1)
    if len(data) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Checkpoint exceeds size limit")
    raw = json.loads(data)
    return _validate(raw)


def _validate(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Checkpoint must be an object")
    version = raw.get("schema_version", 0)
    if type(version) is not int or version < 0 or version > CURRENT_SESSION_SCHEMA_VERSION:
        raise ValueError("Unsupported checkpoint schema version")
    if "metadata" in raw and not isinstance(raw["metadata"], dict):
        raise ValueError("Checkpoint metadata must be an object")
    metadata = raw.get("metadata", {})
    for field in ("workspace", "id"):
        if field in metadata and not isinstance(metadata[field], str):
            raise ValueError(f"Checkpoint metadata {field} must be a string")
    if "messages" in raw and not isinstance(raw["messages"], list):
        raise ValueError("Checkpoint messages must be an array")
    return raw


def save_checkpoint(payload: dict[str, Any]) -> Path:
    data = _validate({**payload, "schema_version": CURRENT_SESSION_SCHEMA_VERSION})
    meta = data.get("metadata") or {}
    workspace = Path(meta["workspace"]) if meta.get("workspace") else None
    session_id = str(meta.get("id") or "") or None
    if workspace is not None and session_id is None:
        raise ValueError("Workspace checkpoint requires a session id")
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text.encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Checkpoint exceeds size limit")
    path = checkpoint_path(workspace=workspace, session_id=session_id)
    write_text_atomic(path, text)
    if workspace is not None:
        write_text_atomic(
            checkpoint_path(workspace=workspace), json.dumps({"session_id": session_id})
        )
    return path


def load_checkpoint(
    *, workspace: Path | None = None, session_id: str | None = None
) -> dict[str, Any] | None:
    if workspace is None:
        return _read(checkpoint_path())
    if session_id is None:
        pointer = _read(checkpoint_path(workspace=workspace))
        if pointer is not None:
            session_id = pointer.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Invalid checkpoint pointer")
    raw = (
        _read(checkpoint_path(workspace=workspace, session_id=session_id))
        if session_id
        else _read(checkpoint_path())
    )
    if raw is None:
        return None
    meta = raw.get("metadata") or {}
    stored_workspace = meta.get("workspace")
    if (
        not isinstance(stored_workspace, str)
        or Path(stored_workspace).resolve() != workspace.resolve()
    ):
        return None
    if session_id is not None and meta.get("id") != session_id:
        raise ValueError("Checkpoint session identity mismatch")
    if session_id is None:
        if not isinstance(meta.get("id"), str) or not meta["id"]:
            return None
        save_checkpoint(raw)  # Migrate a matching legacy payload without deleting its source.
    return raw


def clear_checkpoint(*, workspace: Path | None = None, session_id: str | None = None) -> None:
    # Scoped clears never remove another session's checkpoint or pointer.
    if workspace is not None and session_id is None:
        return
    checkpoint_path(workspace=workspace, session_id=session_id).unlink(missing_ok=True)
