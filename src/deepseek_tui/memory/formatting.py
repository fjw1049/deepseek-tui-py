"""``<relevant-memories>`` block formatting — TencentDB parity."""

from __future__ import annotations

import re

_RELEVANT_MEMORIES_OPEN = "<relevant-memories>"
_RELEVANT_MEMORIES_CLOSE = "</relevant-memories>"
_STRIP_PATTERN = re.compile(
    r"<relevant-memories>[\s\S]*?</relevant-memories>\s*",
    re.IGNORECASE,
)


def wrap_relevant_memories(user_text: str, l1_context: str) -> str:
    """Prepend recall block to the user message (inject_position=user)."""
    body = l1_context.strip()
    if not body:
        return user_text
    block = f"{_RELEVANT_MEMORIES_OPEN}\n{body}\n{_RELEVANT_MEMORIES_CLOSE}"
    if not user_text.strip():
        return block
    return f"{block}\n\n{user_text}"


def wrap_relevant_memories_system_block(l1_context: str) -> str:
    """Volatile system-layer injection (inject_position=system_volatile)."""
    body = l1_context.strip()
    if not body:
        return ""
    return f"{_RELEVANT_MEMORIES_OPEN}\n{body}\n{_RELEVANT_MEMORIES_CLOSE}"


def strip_relevant_memories(text: str) -> str:
    """Remove recall blocks before durable persistence."""
    if _RELEVANT_MEMORIES_OPEN not in text:
        return text
    return _STRIP_PATTERN.sub("", text).strip()
