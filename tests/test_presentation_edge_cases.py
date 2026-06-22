"""Supplementary contract tests for edge cases identified during code review."""

from __future__ import annotations

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.presentation.models import ActionBatchView
from deepseek_tui.presentation.reducer import TurnPresentationReducer, _usable_preface
from deepseek_tui.presentation.semantics import (
    BatchKind,
    Phase,
    classify_batch,
    infer_next_phase,
    batch_intent_text,
)
from deepseek_tui.protocol.responses import ToolCall


def _tool(tool_id: str, name: str = "read_file", **arguments: str) -> ToolCall:
    return ToolCall(id=tool_id, name=name, arguments=arguments)


def _round(*tools: ToolCall, round_idx: int = 0, preface: str | None = None) -> AgentRoundCompleteEvent:
    return AgentRoundCompleteEvent(round_idx=round_idx, tool_calls=tools, preface_text=preface)


# ── semantics edge cases ───────────────────────────────────────────


def test_classify_batch_empty_gives_mixed() -> None:
    assert classify_batch(()) is BatchKind.MIXED


def test_classify_batch_single_read_is_inspect() -> None:
    assert classify_batch((_tool("a", "read_file", path="x.py"),)) is BatchKind.INSPECT


def test_classify_batch_mutate_overrides_reads() -> None:
    tools = (_tool("a", "read_file", path="a.py"), _tool("b", "edit_file", path="b.py"))
    assert classify_batch(tools) is BatchKind.MUTATE


def test_infer_phase_explore_read_to_locate() -> None:
    assert infer_next_phase(Phase.EXPLORE, BatchKind.EXPLORE_READ, has_tool_error=False) is Phase.LOCATE


def test_infer_phase_change_then_search_to_verify() -> None:
    assert infer_next_phase(Phase.CHANGE, BatchKind.SEARCH, has_tool_error=False) is Phase.VERIFY


def test_infer_phase_any_error_to_recover() -> None:
    for phase in Phase:
        assert infer_next_phase(phase, BatchKind.MIXED, has_tool_error=True) is Phase.RECOVER


def test_batch_intent_text_en_locale() -> None:
    tools = (_tool("a", "grep_files", pattern="foo"),)
    text = batch_intent_text(BatchKind.SEARCH, tools, locale="en")
    assert "Search" in text


def test_batch_intent_text_zh_default() -> None:
    tools = (_tool("a", "read_file", path="a.py"), _tool("b", "read_file", path="b.py"))
    text = batch_intent_text(BatchKind.EXPLORE_READ, tools)
    assert "并行" in text


# ── reducer edge cases ─────────────────────────────────────────────


def test_terminal_round_returns_none() -> None:
    """AgentRoundCompleteEvent with no tool_calls is a terminal round."""
    reducer = TurnPresentationReducer()
    result = reducer.on_round_complete(
        AgentRoundCompleteEvent(round_idx=0, tool_calls=())
    )
    assert result is None


def test_reset_clears_state() -> None:
    reducer = TurnPresentationReducer()
    reducer.on_round_complete(_round(_tool("a", path="a.py")))
    assert reducer.round_count == 1
    reducer.reset()
    assert reducer.round_count == 0
    assert reducer.phase is Phase.EXPLORE
    assert reducer.on_tool_result("a", success=True) is None  # mapping cleared


def test_multi_round_phase_progression() -> None:
    reducer = TurnPresentationReducer()
    # Round 1: explore reads -> LOCATE
    batch1 = reducer.on_round_complete(_round(
        _tool("a", "read_file", path="a.py"),
        _tool("b", "read_file", path="b.py"),
    ))
    assert batch1 is not None
    reducer.on_tool_result("a", success=True)
    reducer.on_tool_result("b", success=True)
    assert reducer.phase is Phase.LOCATE

    # Round 2: mutate -> CHANGE
    batch2 = reducer.on_round_complete(_round(
        _tool("c", "edit_file", path="c.py"),
        round_idx=1,
    ))
    assert batch2 is not None
    reducer.on_tool_result("c", success=True)
    assert reducer.phase is Phase.CHANGE

    # Round 3: search after change -> VERIFY
    batch3 = reducer.on_round_complete(_round(
        _tool("d", "grep_files", pattern="test"),
        round_idx=2,
    ))
    assert batch3 is not None
    reducer.on_tool_result("d", success=True)
    assert reducer.phase is Phase.VERIFY


def test_usable_preface_filters_wrappers_and_long_text() -> None:
    assert _usable_preface(None) is None
    assert _usable_preface("") is None
    assert _usable_preface("   ") is None
    assert _usable_preface("a" * 201) is None
    assert _usable_preface("[TOOL_CALL] read_file") is None
    assert _usable_preface("<tool_call>read</tool_call>") is None
    assert _usable_preface("先查看配置文件") == "先查看配置文件"
    # Multi-line: only first line
    assert _usable_preface("第一行\n第二行\n第三行") == "第一行"


def test_preface_text_used_as_intent() -> None:
    reducer = TurnPresentationReducer(locale="zh")
    batch = reducer.on_round_complete(
        _round(
            _tool("a", "read_file", path="a.py"),
            _tool("b", "read_file", path="b.py"),
            preface="先查看事件系统的定义",
        )
    )
    assert batch is not None
    assert batch.intent_text == "先查看事件系统的定义"


def test_sandbox_denied_completes_batch() -> None:
    """SandboxDenied flows through on_tool_denied -> terminal."""
    reducer = TurnPresentationReducer()
    batch = reducer.on_round_complete(
        _round(_tool("a", "exec_shell", command="rm -rf /"))
    )
    assert batch is not None
    completed = reducer.on_tool_denied("a")
    assert completed is batch
    assert completed.status == "partial_fail"
    assert completed.denied_ids == {"a"}


def test_mark_non_collapsible_prevents_collapse() -> None:
    reducer = TurnPresentationReducer()
    batch = reducer.on_round_complete(
        _round(_tool("a", path="a.py"), _tool("b", path="b.py"), _tool("c", path="c.py"))
    )
    assert batch is not None
    reducer.mark_non_collapsible("b")
    assert not batch.can_collapse

    # Complete all tools
    reducer.on_tool_result("a", success=True)
    reducer.on_tool_result("b", success=True)
    completed = reducer.on_tool_result("c", success=True)
    assert completed is batch
    assert not completed.can_collapse


# ── ActionBatchView edge cases ─────────────────────────────────────


def test_action_batch_view_idempotent_receive() -> None:
    batch = ActionBatchView(
        round_idx=0,
        expected_tool_ids=("a", "b"),
        phase="explore",
        intent_text=None,
        batch_summary="test",
        batch_kind="explore_read",
    )
    assert batch.receive_terminal("a", status="done") is False  # not terminal yet
    assert batch.receive_terminal("a", status="done") is False  # idempotent - already recorded
    assert batch.receive_terminal("b", status="done") is True   # now terminal
    assert batch.status == "done"


def test_action_batch_view_unknown_id() -> None:
    batch = ActionBatchView(
        round_idx=0,
        expected_tool_ids=("a",),
        phase="explore",
        intent_text=None,
        batch_summary="test",
        batch_kind="explore_read",
    )
    assert batch.receive_terminal("unknown", status="done") is False
    assert batch.status == "running"  # unchanged
