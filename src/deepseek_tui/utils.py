"""Shared utility functions used across the deepseek-tui package.

Mirrors common patterns from crates/tui/src/utils.rs.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, value: Any) -> None:
    """Write a JSON-serialisable value to *path* atomically (write-tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def summarize_text(text: str, limit: int = 280) -> str:
    """Truncate *text* to *limit* chars, appending '...' if needed.

    Mirrors Rust ``summarize_text`` (runtime_threads.rs:2613-2628).
    Strips control chars except \\n and \\t.
    """
    take = max(limit - 3, 0)
    count = 0
    out: list[str] = []
    for ch in text:
        if count >= take:
            out.append("...")
            return "".join(out)
        if ch.isspace() or not (ch < " " or ch == "\x7f"):
            out.append(ch)
            count += 1
    return "".join(out)
