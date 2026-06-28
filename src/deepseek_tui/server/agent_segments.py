"""Agent message segment semantics for Workbench turn items."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message

AGENT_SEGMENT_KEY = "agent_segment"
MID_TURN_PREFACE = "mid_turn_preface"
FINAL_ANSWER = "final_answer"

REASONING_OMITTED_MARKER = "(reasoning omitted)"

# Prepended when a terminal round produced no answer `content` and we fall back
# to showing the model's raw reasoning as the final answer. Without it the
# chain-of-thought is presented as if it were a clean reply (looks messy and
# is often length-truncated). Surfaced as a short markdown note.
REASONING_FALLBACK_NOTICE = (
    "> ⚠️ 本轮未生成正式回复，以下为模型的推理内容（可能不完整或被截断）。"
)


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
) -> tuple[str | None, bool]:
    """Prefer visible text; on reasoning-only terminal rounds use thinking.

    Returns ``(display_text, is_raw_reasoning_fallback)``. The boolean is True
    only when the returned text is unprocessed raw reasoning (no content was
    produced AND no ``(reasoning omitted)`` protocol marker was present).
    Callers use this to distinguish an accidental budget-truncation fallback
    from a model that intentionally placed its answer inside the thinking block.
    """
    if text and text.strip():
        return text.strip(), False
    if not thinking or not thinking.strip():
        return None, False
    raw = thinking.strip()
    if REASONING_OMITTED_MARKER in raw:
        tail = raw.split(REASONING_OMITTED_MARKER, 1)[1].strip()
        if tail:
            return tail, False
    return raw, True
