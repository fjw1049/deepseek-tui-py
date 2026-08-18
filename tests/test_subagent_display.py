"""Tests for sub-agent display sanitization and context compaction."""

from __future__ import annotations

import json

from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.tools.registry import ToolResult
from deepseek_tui.tui.sanitize import strip_subagent_sentinels


def test_strip_subagent_sentinels_removes_complete_tag() -> None:
    raw = (
        "File missing.\n"
        '<deepseek:subagent.done>{"agent_id":"agent_x","summary":"File missing."}'
        "</deepseek:subagent.done>"
    )
    assert strip_subagent_sentinels(raw) == "File missing.\n"


def test_strip_subagent_sentinels_removes_partial_open_tag() -> None:
    partial = 'Done.\n<deepseek:subagent.done>{"agent_id":"agent_x"'
    assert strip_subagent_sentinels(partial) == "Done.\n"


def test_compact_agent_result_leads_with_result_body() -> None:
    payload = {
        "agent_id": "agent_cfc565bd",
        "agent_type": "explore",
        "status": {"completed": ""},
        "result": "scratch/probe.txt does not exist.",
        "steps_taken": 2,
        "duration_ms": 8400,
    }
    compacted = compact_tool_result_for_context(
        "deepseek-v4-pro",
        "agent",
        ToolResult(success=True, content=json.dumps(payload)),
    )
    assert "result: scratch/probe.txt does not exist." in compacted
    assert compacted.index("result:") < compacted.index("id=agent_cfc565bd")
    assert "stats:" not in compacted
    assert "steps=2" in compacted
