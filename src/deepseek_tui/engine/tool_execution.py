"""Low-level tool execution helpers for the engine turn loop.

Mirrors `crates/tui/src/core/engine/tool_execution.rs:1-298`.

Keeps the mechanics of audit logging, execution locking, and MCP dispatch
out of ``engine.py``; the engine still owns planning, approval, and how
tool results are written back into session state.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- Audit logging (Rust tool_execution.rs:11-26) ------------------------


def emit_tool_audit(event: dict[str, Any]) -> None:
    """Append a JSONL audit line to ``$DEEPSEEK_TOOL_AUDIT_LOG`` if set.

    Silent no-op when the env var is unset or the write fails.
    """
    path_str = os.environ.get("DEEPSEEK_TOOL_AUDIT_LOG")
    if not path_str:
        return
    try:
        line = json.dumps(event, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return
    path = Path(path_str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


