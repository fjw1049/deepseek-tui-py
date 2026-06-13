"""Agent message segment semantics for Workbench turn items."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message

AGENT_SEGMENT_KEY = "agent_segment"
MID_TURN_PREFACE = "mid_turn_preface"
FINAL_ANSWER = "final_answer"

REASONING_OMITTED_MARKER = "(reasoning omitted)"


def assistant_thinking_text(message: Message | None) -> str | None:
    if message is None:
        return None
    from deepseek_tui.protocol.messages import ThinkingBlock

    parts: list[str] = []
    for block in message.content:
        if isinstance(block, ThinkingBlock):
            text = block.thinking.strip()
            if text:
                parts.append(text)
    joined = "\n".join(parts).strip()
    return joined or None


def extract_terminal_display_text(
    *,
    text: str | None,
    thinking: str | None,
) -> str | None:
    """Prefer visible text; on reasoning-only terminal rounds use thinking."""
    if text and text.strip():
        return text.strip()
    if not thinking or not thinking.strip():
        return None
    raw = thinking.strip()
    if REASONING_OMITTED_MARKER in raw:
        tail = raw.split(REASONING_OMITTED_MARKER, 1)[1].strip()
        if tail:
            return tail
    return raw
