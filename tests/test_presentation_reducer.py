"""Contract tests for the presentation-layer batch lifecycle."""

from __future__ import annotations

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.presentation.reducer import TurnPresentationReducer
from deepseek_tui.presentation.semantics import (
    BatchKind,
    Phase,
    batch_intent_text,
    classify_batch,
    resolve_narration_locale,
)
from deepseek_tui.protocol.responses import ToolCall


def _tool(tool_id: str, name: str = "read_file", **arguments: str) -> ToolCall:
    return ToolCall(id=tool_id, name=name, arguments=arguments)


def _round(*tools: ToolCall, round_idx: int = 0) -> AgentRoundCompleteEvent:
    return AgentRoundCompleteEvent(round_idx=round_idx, tool_calls=tools)


def test_semantics_classifies_read_batch_and_localizes_summary() -> None:
    tools = (_tool("a", path="a.py"), _tool("b", path="b.py"))

    assert classify_batch(tools) is BatchKind.EXPLORE_READ
    assert "并行查看" in batch_intent_text(BatchKind.EXPLORE_READ, tools, locale="zh")
    assert resolve_narration_locale("请检查这两个模块", config_locale="zh") == "zh"
    assert resolve_narration_locale("请检查这两个模块", config_locale="en") == "en"


def test_batch_completes_only_after_every_declared_tool_result() -> None:
    reducer = TurnPresentationReducer(locale="zh")
    batch = reducer.on_round_complete(
        _round(
            _tool("a", path="a.py"),
            _tool("b", path="b.py"),
            _tool("c", path="c.py"),
        )
    )

    assert batch is not None
    assert batch.status == "running"
    assert reducer.on_tool_result("a", success=True) is None
    assert reducer.on_tool_result("b", success=True) is None

    completed = reducer.on_tool_result("c", success=True)

    assert completed is batch
    assert completed.status == "done"
    assert completed.is_terminal


def test_parallel_results_may_arrive_out_of_order() -> None:
    reducer = TurnPresentationReducer(locale="en")
    batch = reducer.on_round_complete(
        _round(
            _tool("a", path="a.py"),
            _tool("b", path="b.py"),
            _tool("c", path="c.py"),
        )
    )

    assert reducer.on_tool_result("c", success=True) is None
    assert reducer.on_tool_result("a", success=True) is None
    assert reducer.on_tool_result("b", success=True) is batch


def test_failed_result_marks_batch_and_moves_reducer_to_recovery() -> None:
    reducer = TurnPresentationReducer(locale="zh")
    batch = reducer.on_round_complete(
        _round(_tool("a", path="a.py"), _tool("b", path="b.py"))
    )

    assert reducer.on_tool_result("a", success=True) is None
    completed = reducer.on_tool_result("b", success=False)

    assert completed is batch
    assert completed is not None
    assert completed.status == "partial_fail"
    assert completed.has_error is True
    assert reducer.phase is Phase.RECOVER


def test_approval_marks_batch_non_collapsible_and_denial_is_terminal() -> None:
    reducer = TurnPresentationReducer(locale="zh")
    batch = reducer.on_round_complete(
        _round(_tool("a", "exec_shell", command="rm generated.txt"))
    )

    reducer.on_tool_approval_required("a")
    completed = reducer.on_tool_denied("a")

    assert completed is batch
    assert completed is not None
    assert completed.status == "partial_fail"
    assert completed.has_approval is True
    assert completed.denied_ids == {"a"}
    assert completed.can_collapse is False


def test_completed_batch_ignores_duplicate_and_unknown_results() -> None:
    reducer = TurnPresentationReducer(locale="zh")
    batch = reducer.on_round_complete(_round(_tool("a", path="a.py")))

    assert reducer.on_tool_result("unknown", success=True) is None
    assert reducer.on_tool_result("a", success=True) is batch
    assert reducer.on_tool_result("a", success=True) is None


def test_turn_cancel_closes_active_batch_without_reporting_completion() -> None:
    reducer = TurnPresentationReducer(locale="zh")
    batch = reducer.on_round_complete(
        _round(_tool("a", path="a.py"), _tool("b", path="b.py"))
    )

    cancelled = reducer.on_turn_cancelled()

    assert cancelled is batch
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert reducer.on_tool_result("a", success=True) is None
