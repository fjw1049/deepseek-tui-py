"""Content safety scan for curated memory writes."""

from __future__ import annotations

import re

_BLOCKED_PATTERNS = (
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are", re.IGNORECASE),
)


def scan_memory_content(text: str) -> tuple[bool, str]:
    """Return (ok, reason). Shared by curated store and L1 extraction."""
    cleaned = text.strip()
    if not cleaned:
        return False, "empty content"
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(cleaned):
            return False, f"blocked pattern: {pattern.pattern}"
    return True, ""
