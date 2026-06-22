"""Focused TUI tests for intent narration and inline batch collapsing."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from deepseek_tui.presentation.models import ActionBatchView, ToolActionView
from deepseek_tui.tui.dialogs import UserInputDialogState
from deepseek_tui.tui.input import ComposerHint
from deepseek_tui.tui.tool_cell import InlineToolCell
from deepseek_tui.tui.transcript import (
    Transcript,
    _ActionBatchCell,
    _AssistantCell,
    _IntentCell,
    _is_noise_text,
)


def _batch(*tool_ids: str) -> ActionBatchView:
    batch = ActionBatchView(
        round_idx=0,
        expected_tool_ids=tool_ids,
        phase="locate",
        intent_text="先查看相关文件",
        batch_summary="并行查看相关文件",
        batch_kind="explore_read",
    )
    for tool_id in tool_ids:
        batch.receive_terminal(tool_id, status="done")
    return batch


def test_noise_filter_keeps_narration_and_rejects_symbol_fragments() -> None:
    assert _is_noise_text("...!!!") is True
    assert _is_noise_text("先查看事件处理逻辑") is False


def test_transitional_assistant_becomes_intent_cell(monkeypatch: object) -> None:
    transcript = Transcript()
    assistant = _AssistantCell()
    assistant.append("先读取两个相关模块，再核对事件顺序。")
    transcript._current_assistant = assistant
    mounted: list[tuple[object, str]] = []

    monkeypatch.setattr(_AssistantCell, "remove", lambda self: None)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        transcript,
        "_mount_cell",
        lambda widget, cell_type: mounted.append((widget, cell_type)),
    )

    transcript._discard_transitional_assistant()

    assert len(mounted) == 1
    assert isinstance(mounted[0][0], _IntentCell)
    assert mounted[0][1] == "intent"


def test_completed_inline_batch_collapses_to_one_cell(monkeypatch: object) -> None:
    transcript = Transcript()
    tool_ids = ("a", "b", "c")
    for tool_id in tool_ids:
        cell = InlineToolCell("read_file", tool_id, {"path": f"{tool_id}.py"})
        cell.set_result(f"content for {tool_id}", success=True)
        transcript._tool_cells[tool_id] = cell
    mounted: list[tuple[object, str]] = []

    monkeypatch.setattr(InlineToolCell, "remove", lambda self: None)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        transcript,
        "_mount_and_scroll",
        lambda widget, cell_type: mounted.append((widget, cell_type)),
    )

    transcript.try_collapse_batch(_batch(*tool_ids))

    assert transcript._tool_cells == {}
    assert len(mounted) == 1
    assert isinstance(mounted[0][0], _ActionBatchCell)
    assert mounted[0][1] == "batch"


def test_approval_batch_is_not_collapsed(monkeypatch: object) -> None:
    transcript = Transcript()
    tool_ids = ("a", "b", "c")
    for tool_id in tool_ids:
        cell = InlineToolCell("read_file", tool_id, {"path": f"{tool_id}.py"})
        cell.set_result("ok", success=True)
        transcript._tool_cells[tool_id] = cell
    batch = _batch(*tool_ids)
    batch.mark_approval_required("a")
    mounted: list[object] = []
    monkeypatch.setattr(  # type: ignore[attr-defined]
        transcript,
        "_mount_and_scroll",
        lambda widget, cell_type: mounted.append(widget),
    )

    transcript.try_collapse_batch(batch)

    assert mounted == []
    assert set(transcript._tool_cells) == set(tool_ids)


def test_error_batch_cell_starts_expanded() -> None:
    action = ToolActionView(
        tool_call_id="a",
        tool_name="read_file",
        status="failed",
        summary="a.py",
        detail="boom",
        started_at=0.0,
        finished_at=1.0,
        success=False,
    )
    cell = _ActionBatchCell("读取文件", [action], 1.0, has_error=True)

    assert cell._collapsed is False


def test_user_input_state_collects_multiple_answers() -> None:
    state = UserInputDialogState(
        [
            {"id": "scope", "question": "Scope?"},
            {"id": "style", "question": "Style?"},
        ]
    )

    assert state.answer("TUI") is False
    assert state.answer("Compact") is True
    assert state.response() == {
        "answers": [
            {"question_id": "scope", "value": "TUI"},
            {"question_id": "style", "value": "Compact"},
        ]
    }


def test_composer_hint_tracks_current_and_next_steps() -> None:
    hint = ComposerHint()

    hint.set_progress("实现 reducer", "编写集成测试")

    assert hint._current_step == "实现 reducer"
    assert hint._next_step == "编写集成测试"


class _TranscriptHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield Transcript()


@pytest.mark.asyncio
async def test_transcript_runtime_replaces_intent_and_completed_batch() -> None:
    app = _TranscriptHarness()
    async with app.run_test(size=(100, 40)) as pilot:
        transcript = app.query_one(Transcript)
        transcript.start_assistant_message()
        transcript.append_delta("先并行读取三个模块，确认事件链。")
        for tool_id in ("a", "b", "c"):
            transcript.add_tool_call(
                tool_id,
                "read_file",
                {"path": f"{tool_id}.py"},
            )
        await pilot.pause()

        assert len(transcript.query(_IntentCell)) == 1
        assert len(transcript.query(InlineToolCell)) == 3

        batch = _batch("a", "b", "c")
        for tool_id in batch.expected_tool_ids:
            transcript.update_tool_result(tool_id, "ok", True)
        transcript.try_collapse_batch(batch)
        await pilot.pause()

        assert len(transcript.query(InlineToolCell)) == 0
        assert len(transcript.query(_ActionBatchCell)) == 1
