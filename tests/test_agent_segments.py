"""Tests for agent segment helpers."""

from __future__ import annotations

from deepseek_tui.protocol.messages import Message, Role, TextBlock, ThinkingBlock
from deepseek_tui.server.agent_segments import assistant_thinking_text
def test_assistant_thinking_text_collects_thinking_blocks() -> None:
    msg = Message(
        role=Role.ASSISTANT,
        content=[
            ThinkingBlock(thinking="plan"),
            TextBlock(text="visible"),
        ],
    )
    assert assistant_thinking_text(msg) == "plan"
