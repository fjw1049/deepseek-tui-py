"""Tests for phase-bridge narration helpers."""

from __future__ import annotations

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.phase_bridge import (
    NARRATION_TOOL_NAME,
    BatchKind,
    NarrationPlan,
    Phase,
    ProcessIntent,
    ReasoningSegment,
    TurnNarrationState,
    build_intent_bundle,
    build_process_intent,
    classify_batch,
    contains_tool_name,
    extract_anchors,
    extract_confirmed_facts,
    gate_decision,
    narration_tool_schema,
    plan_from_arguments,
    render_plan,
    resolve_narration_locale,
    template_narration,
    validate_plan,
)


def _segment(text: str = "x" * 220, item_id: str = "item_reason") -> ReasoningSegment:
    return ReasoningSegment(item_id=item_id, text=text)


def _tool(name: str = "read_file", **args: str) -> ToolCall:
    return ToolCall(id="tc1", name=name, arguments=dict(args) if args else {})


def test_gate_skips_empty_tools() -> None:
    state = TurnNarrationState()
    assert gate_decision(
        state=state,
        segment=_segment(),
        tool_calls=(),
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
    ) == "skip"


def test_gate_skips_homogeneous_parallel_reads_without_phase_change() -> None:
    state = TurnNarrationState(phase=Phase.LOCATE)
    tools = (
        _tool("read_file", path="a.py"),
        _tool("read_file", path="b.py"),
        _tool("read_file", path="c.py"),
    )
    assert classify_batch(tools) == BatchKind.EXPLORE_READ
    assert gate_decision(
        state=state,
        segment=_segment(),
        tool_calls=tools,
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
    ) == "skip"


def test_gate_allows_explore_read_on_phase_transition() -> None:
    state = TurnNarrationState(phase=Phase.EXPLORE)
    tools = (
        _tool("read_file", path="a.py"),
        _tool("read_file", path="b.py"),
    )
    assert classify_batch(tools) == BatchKind.EXPLORE_READ
    assert gate_decision(
        state=state,
        segment=_segment(),
        tool_calls=tools,
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
    ) == "compute"


def test_gate_compute_for_mutate_batch() -> None:
    state = TurnNarrationState()
    tools = (_tool("write_file", path="src/foo.py"),)
    assert gate_decision(
        state=state,
        segment=_segment(),
        tool_calls=tools,
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
    ) == "compute"


def test_gate_respects_publish_cap() -> None:
    state = TurnNarrationState(published_count=12)
    assert gate_decision(
        state=state,
        segment=_segment(),
        tool_calls=(_tool("write_file", path="x"),),
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
    ) == "skip"


def test_validate_plan_rejects_tool_names() -> None:
    plan = NarrationPlan(
        publish=True,
        phase="locate",
        finding="接下来 read_file",
        next_goal="验证 UI",
    )
    assert validate_plan(plan) is False
    assert render_plan(plan) is None


def test_render_plan_joins_finding_and_next_goal() -> None:
    plan = NarrationPlan(
        publish=True,
        phase="locate",
        finding="已确认服务端与前端 reasoning 切段时机不同",
        next_goal="接下来核对 reload 路径是否一致",
    )
    text = render_plan(plan, locale="zh")
    assert text is not None
    assert "已确认" in text
    assert "reload" in text
    assert not contains_tool_name(text)


def test_validate_plan_accepts_any_language() -> None:
    # Language/style belong to the narration model (locale is in the request);
    # validation stays structural so any provider/language combination works.
    plan = NarrationPlan(
        publish=True,
        phase="explore",
        finding="Confirmed the router registers all endpoints.",
        next_goal="Verify the handler chain next.",
    )
    assert validate_plan(plan, locale="zh") is True


def test_narration_tool_schema_shape() -> None:
    schema = narration_tool_schema()
    assert schema["function"]["name"] == NARRATION_TOOL_NAME
    params = schema["function"]["parameters"]
    assert set(params["required"]) == {"publish", "finding"}
    assert set(params["properties"]) == {"publish", "phase", "finding", "next_goal"}


def test_plan_from_arguments_round_trip() -> None:
    plan = plan_from_arguments(
        {
            "publish": True,
            "phase": "verify",
            "finding": "已确认修改生效",
            "next_goal": "运行测试",
        }
    )
    assert plan.publish is True
    assert plan.phase == "verify"
    assert plan.finding == "已确认修改生效"
    assert plan.next_goal == "运行测试"


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


def test_extract_confirmed_facts_from_tool_summaries() -> None:
    facts = extract_confirmed_facts(
        ["read_file: src/deepseek_tui/server/threads.py\nclass RuntimeThreadManager"]
    )
    assert facts
    assert "threads.py" in facts[0]


def test_build_intent_bundle_uses_user_language_intent() -> None:
    state = TurnNarrationState(phase=Phase.LOCATE)
    bundle = build_intent_bundle(
        user_goal="梳理架构",
        state=state,
        segment=_segment(),
        tool_calls=(_tool("read_file", path="src/deepseek_tui/server/threads.py"),),
        recent_tool_results=(),
        locale="zh",
    )
    assert "threads.py" in bundle.batch_intent
    assert bundle.phase == "locate"


def test_agent_round_complete_defaults_empty_tools() -> None:
    event = AgentRoundCompleteEvent(round_idx=0)
    assert event.tool_calls == ()


def test_resolve_narration_locale_follows_settings_only() -> None:
    # Message script must not override Workbench / config.ui.locale.
    assert (
        resolve_narration_locale(
            "Explain how the workflow engine orchestrates turns.",
            config_locale="zh",
        )
        == "zh"
    )
    assert (
        resolve_narration_locale(
            "深入研究代码，了解整个 workflow 的工作原理",
            config_locale="en",
        )
        == "en"
    )
    assert resolve_narration_locale("", config_locale="auto") == "zh"
    assert resolve_narration_locale("", config_locale="zh") == "zh"


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
