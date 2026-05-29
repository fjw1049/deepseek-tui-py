"""Turn capture quality gates — MEMORY_INTEGRATION v3 §3.3."""

from __future__ import annotations

import re

_CONFIRM_ONLY = re.compile(
    r"^(?:好的?|继续|ok|okay|yes|yep|sure|thanks?|thank you|got it|"
    r"明白|知道了|嗯|行|可以|收到)[\s!.。]*$",
    re.IGNORECASE,
)


def should_capture_turn(
    user_text: str,
    *,
    had_tool_calls: bool,
    success: bool,
    min_chars: int = 20,
    skip_slash: bool = True,
    skip_confirmations: bool = True,
) -> bool:
    if not success:
        return False
    if had_tool_calls:
        return True
    text = user_text.strip()
    if skip_slash and text.startswith("/"):
        return False
    if len(text) < min_chars:
        return False
    if skip_confirmations and _CONFIRM_ONLY.match(text):
        return False
    return True
