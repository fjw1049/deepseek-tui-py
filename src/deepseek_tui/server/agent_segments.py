"""Agent message segment semantics for Workbench turn items."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message

AGENT_SEGMENT_KEY = "agent_segment"
MID_TURN_PREFACE = "mid_turn_preface"
FINAL_ANSWER = "final_answer"

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
