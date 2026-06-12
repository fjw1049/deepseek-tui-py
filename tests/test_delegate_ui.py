"""Tests for sub-agent delegate UI rendering."""

from __future__ import annotations

from deepseek_tui.tui.cards import (
    AgentLifecycle,
    DelegateCard,
    _summary_for_display,
)
from deepseek_tui.tui.tool_cell import ToolCell, _extract_agent_id


def test_extract_agent_id_from_spawn_text() -> None:
    assert _extract_agent_id("spawned agent_0d2b2a3a [explore]") == "agent_0d2b2a3a"


def test_extract_agent_id_from_json() -> None:
    raw = '{"agent_id":"agent_abc","agent_type":"explore"}'
    assert _extract_agent_id(raw) == "agent_abc"


def test_summary_for_display_prefers_summary_section() -> None:
    raw = (
        "### SUMMARY\n"
        "读取了 scratch/probe.txt，内容为一行测试文本。\n"
        "### EVIDENCE\n"
        "- scratch/probe.txt:1: Hello"
    )
    assert _summary_for_display(raw) == "读取了 scratch/probe.txt，内容为一行测试文本。"


def test_delegate_card_renders_short_id_and_summary() -> None:
    card = DelegateCard(
        agent_id="agent_0d2b2a3a",
        agent_type="explore",
        status=AgentLifecycle.COMPLETED,
        summary=(
            "### SUMMARY\n"
            "文件内容已读取。\n"
            "### EVIDENCE\n"
            "- scratch/probe.txt:1: hello"
        ),
    )
    text = card.render_text()
    assert "agent_0d2b2a" in text
    assert "文件内容已读取。" in text
    assert "### EVIDENCE" not in text


def test_agent_spawn_tool_cell_is_compact_single_line() -> None:
    cell = ToolCell("agent_spawn", "call123", arguments={"type": "explore"})
    cell.set_result("spawned agent_0d2b2a3a [explore]", success=True)
    rendered = str(cell.render())
    assert "hidden:" not in rendered
    assert "agent_0d2b2a" in rendered
    assert "delegate" in rendered
