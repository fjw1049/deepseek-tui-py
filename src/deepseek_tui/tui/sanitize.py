"""Sanitize assistant text before rendering in the TUI."""

from __future__ import annotations

import re

_SUBAGENT_DONE_RE = re.compile(
    r"<deepseek:subagent\.done>.*?</deepseek:subagent\.done>",
    re.DOTALL,
)
_SUBAGENT_DONE_OPEN_RE = re.compile(r"<deepseek:subagent\.done>.*\Z", re.DOTALL)


def strip_subagent_sentinels(text: str) -> str:
    """Remove internal sub-agent completion sentinels from user-visible text."""
    cleaned = _SUBAGENT_DONE_RE.sub("", text)
    cleaned = _SUBAGENT_DONE_OPEN_RE.sub("", cleaned)
    return cleaned
