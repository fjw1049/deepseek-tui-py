"""Tests for automation delivery formatting."""

from __future__ import annotations

from deepseek_tui.automation.delivery import (
    assistant_message_text,
    classify_task_error_for_user,
    format_delivery_body,
    sanitize_delivery_text,
    should_skip_delivery_for_error,
)
from deepseek_tui.tools.task import STALE_RESTART_ERROR
from deepseek_tui.protocol.messages import Message, TextBlock, ThinkingBlock


def test_assistant_message_text_skips_thinking() -> None:
    msg = Message(
        role="assistant",
        content=[
            ThinkingBlock(thinking="internal chain"),
            TextBlock(text="**微博热搜日报**\n1. foo"),
        ],
    )
    assert assistant_message_text(msg) == "**微博热搜日报**\n1. foo"


def test_classify_tool_round_trip_limit() -> None:
    msg = classify_task_error_for_user("Tool round-trip limit exceeded")
    assert "Tool round-trip" not in msg
    assert "步骤过多" in msg


def test_classify_web_search_failed() -> None:
    msg = classify_task_error_for_user("web_search failed: anysearch: timeout")
    assert "ANYSEARCH" in msg or "anysearch" in msg.lower()
    assert "TAVILY" in msg or "tavily" in msg.lower()


def test_sanitize_drops_process_narration() -> None:
    raw = (
        "我来获取微博热搜数据并整理报告。\n"
        "数据获取成功。\n\n"
        "---\n\n"
        "**📱 微博热搜日报 | 2026年5月28日**\n\n"
        "1️⃣ **翘楚定档**（118.9万）"
    )
    out = sanitize_delivery_text(raw)
    assert "我来获取" not in out
    assert "翘楚定档" in out


def test_sanitize_strips_delivery_meta() -> None:
    raw = (
        "报告已生成并通过飞书发送成功。以下是本次摘要：\n\n"
        "## TOP 10\n| 1 | foo |"
    )
    out = sanitize_delivery_text(raw)
    assert "飞书发送" not in out
    assert "TOP 10" in out


def test_format_delivery_failure_no_raw_error() -> None:
    body = format_delivery_body(
        succeeded=False,
        raw_summary="我来查询…",
        automation_name="小米股票",
        error="Tool round-trip limit exceeded",
    )
    assert "Tool round-trip" not in body
    assert "❌ 小米股票" in body


def test_format_delivery_success_empty() -> None:
    body = format_delivery_body(
        succeeded=True,
        raw_summary="   ",
        automation_name="测试",
    )
    assert "测试" in body
    assert "未生成" in body


def test_should_skip_stale_restart_error() -> None:
    assert should_skip_delivery_for_error(STALE_RESTART_ERROR) is True
    assert should_skip_delivery_for_error("Tool round-trip limit exceeded") is False


def test_classify_stale_restart() -> None:
    msg = classify_task_error_for_user(STALE_RESTART_ERROR)
    assert "重启" in msg
    assert "stale" not in msg.lower()
