"""``<relevant-memories>`` block formatting — TencentDB parity."""

from __future__ import annotations

import re
import time

_RELEVANT_MEMORIES_OPEN = "<relevant-memories>"
_RELEVANT_MEMORIES_CLOSE = "</relevant-memories>"
_STRIP_PATTERN = re.compile(
    r"<relevant-memories>[\s\S]*?</relevant-memories>\s*",
    re.IGNORECASE,
)
_INJECTED_CONTEXT_PATTERNS = [
    re.compile(r"<relevant-memories>[\s\S]*?</relevant-memories>\s*", re.IGNORECASE),
    re.compile(r"<user-persona>[\s\S]*?</user-persona>\s*", re.IGNORECASE),
    re.compile(r"<persona>[\s\S]*?</persona>\s*", re.IGNORECASE),
    re.compile(r"<scene-navigation>[\s\S]*?</scene-navigation>\s*", re.IGNORECASE),
    re.compile(r"<relevant-scenes>[\s\S]*?</relevant-scenes>\s*", re.IGNORECASE),
    re.compile(r"<memory-tools-guide>[\s\S]*?</memory-tools-guide>\s*", re.IGNORECASE),
    re.compile(r"<current_task_context>[\s\S]*?</current_task_context>\s*", re.IGNORECASE),
    re.compile(r"<history_task_context[\s\S]*?</history_task_context>\s*", re.IGNORECASE),
]
_BASE64_IMAGE_RE = re.compile(
    r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+",
    re.IGNORECASE,
)
_MEDIA_MARKER_RE = re.compile(r"\[media attached:[^\]]*\]\s*", re.IGNORECASE)
_TIMESTAMP_PREFIX_RE = re.compile(r"^\[[\w\d\-:+ ]+\]\s*", re.MULTILINE)
_REPLY_DIRECTIVE_RE = re.compile(r"\[\[reply_to[^\]]*\]\]\s*", re.IGNORECASE)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.DOTALL)


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


def strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks from assistant text before L1 extraction."""
    return _CODE_BLOCK_RE.sub("", text).strip()


def sanitize_memory_text(text: str) -> str:
    """Clean framework-injected context and media noise before memory persistence."""
    cleaned = text
    for pattern in _INJECTED_CONTEXT_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = _BASE64_IMAGE_RE.sub("", cleaned)
    cleaned = _MEDIA_MARKER_RE.sub("", cleaned)
    cleaned = _REPLY_DIRECTIVE_RE.sub("", cleaned)
    cleaned = _TIMESTAMP_PREFIX_RE.sub("", cleaned)
    cleaned = cleaned.replace("\0", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def format_activity_time(created_at_ms: int) -> str:
    """Human-readable relative time for recall injection."""
    elapsed = int(time.time() * 1000) - created_at_ms
    if elapsed < 0:
        return "刚刚"
    minutes = elapsed // 60_000
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes}分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前"
    days = hours // 24
    if days < 30:
        return f"{days}天前"
    months = days // 30
    return f"{months}个月前"


def escape_memory_xml_tags(text: str) -> str:
    """Escape tags that could break out of memory injection wrappers."""
    return re.sub(
        r"</?(?:user-persona|persona|relevant-memories|scene-navigation|"
        r"relevant-scenes|memory-tools-guide|system|assistant)>",
        lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"),
        text,
        flags=re.IGNORECASE,
    )
