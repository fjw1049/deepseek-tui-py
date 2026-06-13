"""Tests for agent segment helpers."""

from __future__ import annotations

from deepseek_tui.protocol.messages import Message, Role, TextBlock, ThinkingBlock
from deepseek_tui.server.agent_segments import (
    assistant_thinking_text,
    extract_terminal_display_text,
)
from deepseek_tui.server.phase_bridge import usable_preface as phase_usable_preface


def test_extract_terminal_display_text_prefers_text() -> None:
    assert extract_terminal_display_text(text="hello", thinking="hidden") == "hello"


def test_extract_terminal_display_text_uses_thinking_when_no_text() -> None:
    assert extract_terminal_display_text(text=None, thinking="final answer") == "final answer"


def test_extract_terminal_display_text_splits_reasoning_omitted_marker() -> None:
    raw = "internal plan\n(reasoning omitted)\n用户可见正文"
    assert extract_terminal_display_text(text=None, thinking=raw) == "用户可见正文"


def test_assistant_thinking_text_collects_thinking_blocks() -> None:
    msg = Message(
        role=Role.ASSISTANT,
        content=[
            ThinkingBlock(thinking="plan"),
            TextBlock(text="visible"),
        ],
    )
    assert assistant_thinking_text(msg) == "plan"


def test_usable_preface_accepts_short_explore_preface() -> None:
    assert phase_usable_preface("开始探索代码库结构。") == "开始探索代码库结构。"
