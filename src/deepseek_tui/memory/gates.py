"""Turn capture quality gates for memory."""

from __future__ import annotations

_CONFIRMATION_PATTERNS = frozenset({"y", "yes", "ok", "sure", "go ahead", "do it", "proceed"})


def should_capture_turn(
    user_text: str,
    *,
    had_tool_calls: bool,
    success: bool,
    min_chars: int = 20,
    skip_slash: bool = True,
    skip_confirmations: bool = True,
) -> bool:
    """Decide whether a turn is worth capturing to memory."""
    if not success:
        return False
    text = user_text.strip()
    if not text:
        return False
    if skip_slash and text.startswith("/"):
        return False
    if skip_confirmations and text.lower() in _CONFIRMATION_PATTERNS:
        return False
    if len(text) < min_chars and not had_tool_calls:
        return False
    return True


__all__ = ["should_capture_turn"]
