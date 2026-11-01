"""Tests for phase-bridge narration helpers."""

from __future__ import annotations

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.phase_bridge import (
    BatchKind,
    Phase,
    ProcessIntent,
    build_process_intent,
    extract_anchors,
    resolve_narration_locale,
    template_narration,
)


def _tool(name: str = "read_file", **args: str) -> ToolCall:
    return ToolCall(id="tc1", name=name, arguments=dict(args) if args else {})


def test_extract_anchors_from_structured_arguments() -> None:
    anchors = extract_anchors(
        (
            _tool("read_file", path="src/a.py"),
            _tool("grep_files", query="RuntimeThreadManager"),
            _tool("read_file", path="src/a.py"),
        )
    )
    assert anchors == ("src/a.py", "RuntimeThreadManager")


def test_build_process_intent_metadata() -> None:
    intent = build_process_intent(
        scope="pre_tool",
        source="none",
        phase=Phase.LOCATE,
        tool_calls=(
            _tool("read_file", path="src/a.py"),
            _tool("read_file", path="src/b.py"),
        ),
        locale="zh",
    )
    assert isinstance(intent, ProcessIntent)
    meta = intent.to_metadata()
    assert meta["scope"] == "pre_tool"
    assert meta["source"] == "none"
    assert meta["phase"] == "locate"
    assert meta["batch"] == "explore_read"
    assert meta["tool_count"] == 2
    assert meta["anchors"] == ["src/a.py", "src/b.py"]


def test_agent_round_complete_defaults_empty_tools() -> None:
    event = AgentRoundCompleteEvent(round_idx=0)
    assert event.tool_calls == ()


def test_resolve_narration_locale_follows_settings_only() -> None:
    # Message script must not override Workbench / config.ui.locale.
    assert resolve_narration_locale(config_locale="zh") == "zh"
    assert resolve_narration_locale(config_locale="en") == "en"
    assert resolve_narration_locale(config_locale="auto") == "zh"


def test_template_narration_localizes_for_chinese() -> None:
    tools = (_tool("list_dir", path="src"),)
    text = template_narration(locale="zh", batch=BatchKind.EXPLORE_DIR, tool_calls=tools)
    assert text is not None
    assert "浏览" in text
    assert "src" in text


def test_template_narration_localizes_for_english() -> None:
    tools = (_tool("list_dir", path="src"),)
    text = template_narration(locale="en", batch=BatchKind.EXPLORE_DIR, tool_calls=tools)
    assert text is not None
    assert "Survey structure" in text


def test_recovery_does_not_stick_after_successful_work() -> None:
    from deepseek_tui.server.phase_bridge import infer_next_phase
    assert infer_next_phase(Phase.RECOVER, BatchKind.INSPECT, has_tool_error=False) == Phase.LOCATE




def test_a_config_file_from_before_narration_was_removed_still_loads():
    from deepseek_tui.config.models import UiConfig

    UiConfig.model_validate({"process_narration": {"enabled": True, "max_per_turn": 12}})
