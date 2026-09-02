"""Crash-recovery checkpoint persistence for the legacy TUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import user_checkpoints_dir
from deepseek_tui.utils import write_text_atomic

CURRENT_SESSION_SCHEMA_VERSION = 1


def checkpoint_path() -> Path:
    return user_checkpoints_dir() / "latest.json"


def save_checkpoint(payload: dict[str, Any]) -> Path:
    data = {"schema_version": CURRENT_SESSION_SCHEMA_VERSION, **payload}
    path = checkpoint_path()
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
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
    checkpoint_path().unlink(missing_ok=True)
