"""Tests for phase-bridge narration helpers."""

from __future__ import annotations

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.phase_bridge import (
    BatchKind,
    NarrationPlan,
    Phase,
    ReasoningSegment,
    TurnNarrationState,
    batch_intent_text,
    build_intent_bundle,
    classify_batch,
    contains_tool_name,
    decide_and_prepare,
    extract_confirmed_facts,
    gate_decision,
    locale_preface,
    note_published,
    preface_matches_locale,
    render_plan,
    resolve_narration_locale,
    template_narration,
    usable_preface,
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
        preface_text=None,
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
        preface_text=None,
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
    ) == "compute"
    note_published(
        state,
        batch_intent_text(BatchKind.EXPLORE_READ, tools, locale="zh"),
        batch=BatchKind.EXPLORE_READ,
        tool_calls=tools,
    )
    assert gate_decision(
        state=state,
        segment=_segment(item_id="item_reason_2"),
        tool_calls=tools,
        preface_text=None,
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
        preface_text=None,
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
    ) == "compute"


def test_gate_compute_for_first_explore_dir() -> None:
    state = TurnNarrationState()
    tools = (_tool("list_dir", path="src"),)
    preface = "先从项目结构入手，了解整体模块划分"
    decision, immediate = decide_and_prepare(
        state=state,
        segment=_segment(),
        tool_calls=tools,
        preface_text=preface,
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
        locale="zh",
    )
    assert decision == "compute"
    assert immediate is None


def test_gate_compute_for_mutate_batch() -> None:
    state = TurnNarrationState()
    tools = (_tool("apply_patch", path="src/foo.py"),)
    assert gate_decision(
        state=state,
        segment=_segment(),
        tool_calls=tools,
        preface_text=None,
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
    ) == "compute"


def test_gate_respects_publish_cap() -> None:
    state = TurnNarrationState(published_count=12)
    assert gate_decision(
        state=state,
        segment=_segment(),
        tool_calls=(_tool("apply_patch", path="x"),),
        preface_text=None,
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


def test_usable_preface_rejects_tool_names() -> None:
    assert usable_preface("接下来 list_dir src") is None
    assert usable_preface("先从整体结构入手，了解模块划分") is not None


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


def test_resolve_narration_locale_from_chinese_input() -> None:
    assert resolve_narration_locale("深入研究代码，了解整个 workflow 的工作原理") == "zh"


def test_resolve_narration_locale_from_english_input() -> None:
    assert resolve_narration_locale("Explain how the workflow engine orchestrates turns.") == "en"


def test_locale_preface_rejects_english_for_chinese_turn() -> None:
    assert locale_preface("Starting with the project structure.", "zh") is None
    assert preface_matches_locale("Starting with the project structure.", "zh") is False
    assert locale_preface("开始探索代码库结构。", "zh") == "开始探索代码库结构。"


def test_gate_uses_compute_when_preface_language_mismatches() -> None:
    state = TurnNarrationState()
    tools = (_tool("list_dir", path="src"),)
    assert gate_decision(
        state=state,
        segment=_segment(),
        tool_calls=tools,
        preface_text="Starting with the project structure.",
        narrated_ids=set(),
        min_chars=200,
        has_tool_error=False,
        locale="zh",
    ) == "compute"


def test_validate_plan_rejects_wrong_output_language() -> None:
    plan = NarrationPlan(
        publish=True,
        phase="explore",
        finding="Starting with the project structure.",
        next_goal="Read the core modules next.",
    )
    assert validate_plan(plan, locale="zh") is False
    assert render_plan(plan, locale="zh") is None


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
