"""Regression: CJK must not be \\u-escaped before token estimation."""

from __future__ import annotations

from deepseek_tui.engine.context import estimated_input_tokens
from deepseek_tui.protocol.messages import Message, Role, TextBlock


def test_estimated_input_tokens_does_not_inflate_cjk_via_ascii_escape() -> None:
    # ~10k Chinese chars — with ensure_ascii=True this becomes ~60k escaped
    # chars and the char-split estimator reports ~3× too many tokens.
    blob = "众安保险年度报告摘要" * 1000
    messages = [Message(role=Role.TOOL, content=[TextBlock(text=blob)])]

    tokens = estimated_input_tokens(messages)
    # Honest UTF-8 path is well under 20k; the escaped path was ~30k+.
    assert tokens < 20_000
    assert tokens > 1_000
