"""Tests for agent segment helpers."""

from __future__ import annotations

from deepseek_tui.protocol.messages import Message, Role, TextBlock, ThinkingBlock
from deepseek_tui.server.agent_segments import (
    assistant_thinking_text,
    extract_terminal_display_text,
)
def test_extract_terminal_display_text_prefers_text() -> None:
    text, fallback = extract_terminal_display_text(text="hello", thinking="hidden")
    assert text == "hello"
    assert fallback is False


def test_extract_terminal_display_text_uses_thinking_when_no_text() -> None:
    text, fallback = extract_terminal_display_text(text=None, thinking="final answer")
    assert text == "final answer"
    assert fallback is True


def test_extract_terminal_display_text_splits_reasoning_omitted_marker() -> None:
    raw = "internal plan\n(reasoning omitted)\n用户可见正文"
    text, fallback = extract_terminal_display_text(text=None, thinking=raw)
    assert text == "用户可见正文"
    assert fallback is False


def test_assistant_thinking_text_collects_thinking_blocks() -> None:
    msg = Message(
        role=Role.ASSISTANT,
        content=[
            ThinkingBlock(thinking="plan"),
            TextBlock(text="visible"),
        ],
    )
    assert assistant_thinking_text(msg) == "plan"
