"""User-level memory file — mirrors ``crates/tui/src/memory.rs``."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

MAX_MEMORY_SIZE = 100 * 1024

_TRUTHY = frozenset({"1", "on", "true", "yes", "y", "enabled"})
_FALSY = frozenset({"0", "off", "false", "no", "n", "disabled"})


def memory_enabled_from_env() -> bool | None:
    raw = os.getenv("DEEPSEEK_MEMORY", "").strip().lower()
    if not raw:
        return None
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return None


def load(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not content.strip():
        return None
    return content


def as_system_block(content: str, source: Path) -> str | None:
    trimmed = content.strip()
    if not trimmed:
        return None
    display = str(source.expanduser())
    if len(content) > MAX_MEMORY_SIZE:
        omitted = len(content) - MAX_MEMORY_SIZE
        payload = content[:MAX_MEMORY_SIZE]
        payload += f'\n<truncated bytes={omitted} source="{display}">'
    else:
        payload = trimmed
    return f'<user_memory source="{display}">\n{payload}\n</user_memory>'


def compose_block(enabled: bool, path: Path) -> str | None:
    if not enabled:
        return None
    content = load(path)
    if content is None:
        return None
    return as_system_block(content, path)


def append_entry(path: Path, entry: str) -> None:
    """Append a timestamped bullet; strips leading ``#`` from quick-add."""
    text = entry.strip()
    if text.startswith("#"):
        text = text[1:].strip()
    if not text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line = f"- ({stamp}) {text}\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
