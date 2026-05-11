"""Stage 6 polish (2026-05-11) smoke tests.

Pins the cell-level redesign that retired the bare ``You: / Assistant:``
prefix labels. These tests do NOT scrape rendered Rich markup — Textual
mounts the cells and we just verify they don't crash on realistic
payloads (markdown, diff, long output, notice severities) and that the
public API contract is intact.
"""
from __future__ import annotations

from textual.app import App, ComposeResult

from deepseek_tui.tui.widgets.tool_cell import (
    ToolCell,
    _classify,
    _head_tail_preview,
    _looks_like_diff,
    _summarize_args,
)
from deepseek_tui.tui.widgets.transcript import (
    _AssistantCell,
    _NoticeCell,
    _ThinkingCell,
    _TurnDivider,
    _UserCell,
    Transcript,
)


# ── helpers ──────────────────────────────────────────────────────────


class _Harness(App[None]):
    def compose(self) -> ComposeResult:
        yield Transcript()


_DIFF_SAMPLE = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def f():
-    return 1
+    return 2
"""

_LONG_TOOL_OUTPUT = "\n".join(f"line {i:03d}" for i in range(1, 41))


# ── ToolCell pure helpers (no widget mounting) ───────────────────────


def test_classify_known_tools() -> None:
    assert _classify("read_file") == ("▷", "read")
    assert _classify("edit_file") == ("◆", "patch")
    assert _classify("exec_shell") == ("▶", "run")
    assert _classify("grep_files") == ("⌕", "search")


def test_classify_family_fallback() -> None:
    assert _classify("git_status") == ("◈", "git")
    assert _classify("git_pr_create") == ("◈", "git")
    assert _classify("task_anything") == ("◇", "task")
    assert _classify("agent_xyz") == ("◇", "agent")


def test_classify_unknown_default() -> None:
    glyph, verb = _classify("totally_made_up_tool")
    assert glyph == "◇"
    assert verb == "totally_made_up_tool"


def test_summarize_args_picks_first_nonempty() -> None:
    assert _summarize_args({"path": "/x/y.py"}) == "/x/y.py"
    assert _summarize_args({"empty": "", "path": "/x/y.py"}) == "/x/y.py"
    assert _summarize_args(None) is None
    assert _summarize_args({}) is None


def test_summarize_args_truncates_long_value() -> None:
    summary = _summarize_args({"command": "echo " + "x" * 200})
    assert summary is not None
    assert len(summary) <= 56
    assert summary.endswith("…")


def test_summarize_args_first_line_only() -> None:
    summary = _summarize_args({"text": "line one\nline two\nline three"})
    assert summary == "line one"


def test_looks_like_diff_detects_unified() -> None:
    assert _looks_like_diff(_DIFF_SAMPLE) is True


def test_looks_like_diff_rejects_plain() -> None:
    assert _looks_like_diff("just some output\nwith two lines") is False
    assert _looks_like_diff("") is False
    # Hunk-style line alone without --- / +++ should not count.
    assert _looks_like_diff("@@ matched 3 occurrences @@") is False


def test_head_tail_preview_short_passthrough() -> None:
    lines, omitted = _head_tail_preview("a\nb\nc")
    assert lines == ["a", "b", "c"]
    assert omitted == 0


def test_head_tail_preview_samples_head_and_tail() -> None:
    visible, omitted = _head_tail_preview(_LONG_TOOL_OUTPUT)
    assert omitted > 0
    assert "…" in visible
    # Head + ellipsis + tail
    assert visible[0] == "line 001"
    assert visible[-1] == "line 040"


# ── Cell mounting smoke ──────────────────────────────────────────────


async def test_user_cell_mounts_and_renders() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_user_message("Hello with **markdown** that should stay literal")
        # Two children expected: the _UserCell we just mounted.
        users = list(tx.query(_UserCell))
        assert len(users) == 1


async def test_assistant_cell_streams_markdown() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.start_assistant_message()
        tx.append_delta("# Heading\n\n")
        tx.append_delta("Some **bold** and `code`.\n\n")
        tx.append_delta("```python\nprint('hi')\n```\n")
        tx.finalize_message()
        # No exception; buffer cleared on finalize.
        assert tx._current_buffer == ""
        # Turn divider mounted at end of turn.
        assert len(list(tx.query(_TurnDivider))) == 1


async def test_thinking_cell_collapses_when_show_thinking_true() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.show_thinking = True
        tx.start_assistant_message()
        for i in range(10):
            tx.append_thinking(f"thinking step {i}\n")
        tx.append_delta("Done.")
        tx.finalize_message()
        # Thinking cell persists in history (collapsed, not dropped).
        cells = list(tx.query(_ThinkingCell))
        assert len(cells) == 1
        # Auto-collapsed on finalize so the user lands on the assistant
        # answer; one click re-expands it.
        assert cells[0]._collapsed is True
        assert cells[0]._finalized is True


async def test_thinking_cell_streaming_stays_expanded() -> None:
    """Mid-stream thinking must stay visible — the user wants to watch
    the model reason live, even though the body auto-collapses once
    finalize fires."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.start_assistant_message()
        tx.append_thinking("Let me look at this...\n")
        cell = list(tx.query(_ThinkingCell))[0]
        assert cell._collapsed is False
        assert cell._finalized is False


async def test_thinking_cell_dropped_when_show_thinking_false() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)) as pilot:
        tx = app.query_one(Transcript)
        tx.show_thinking = False
        tx.start_assistant_message()
        tx.append_thinking("internal noise that the user opted out of")
        tx.append_delta("Answer.")
        tx.finalize_message()
        # ``Widget.remove`` is scheduled on the event loop; pause once
        # so Textual processes the pending remove before we inspect.
        await pilot.pause()
        assert len(list(tx.query(_ThinkingCell))) == 0


async def test_tool_cell_renders_long_output_with_truncation() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_tool_call("tc-long", "exec_shell", {"command": "seq 1 40"})
        tx.update_tool_result("tc-long", _LONG_TOOL_OUTPUT, success=True)
        cells = list(tx.query(ToolCell))
        assert len(cells) == 1
        # Full result is retained (not truncated to 200 chars).
        assert cells[0]._result == _LONG_TOOL_OUTPUT
        assert cells[0]._status == "done"
        # Auto-collapsed on completion so the final assistant message
        # stays the visual focus.
        assert cells[0]._collapsed is True


async def test_tool_cell_click_toggles_collapsed() -> None:
    """Clicking the cell flips collapsed ↔ expanded so the user can
    re-inspect output that was auto-hidden on completion."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_tool_call("tc-toggle", "exec_shell", {"command": "ls"})
        tx.update_tool_result("tc-toggle", "a\nb\nc", success=True)
        cell = list(tx.query(ToolCell))[0]
        assert cell._collapsed is True
        # Simulate a click — calls the same handler the mouse would.
        cell.on_click(None)  # type: ignore[arg-type]
        assert cell._collapsed is False
        cell.on_click(None)  # type: ignore[arg-type]
        assert cell._collapsed is True


async def test_tool_cell_running_stays_expanded() -> None:
    """A tool cell that hasn't completed yet must stay expanded so the
    user can see what it's working on."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_tool_call("tc-run", "exec_shell", {"command": "long_job"})
        cell = list(tx.query(ToolCell))[0]
        assert cell._status == "running"
        assert cell._collapsed is False


async def test_tool_cell_renders_diff_result() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_tool_call("tc-diff", "git_diff", {"file": "foo.py"})
        tx.update_tool_result("tc-diff", _DIFF_SAMPLE, success=True)
        cells = list(tx.query(ToolCell))
        assert cells[0]._status == "done"
        # Diff routing should have been chosen.
        assert _looks_like_diff(cells[0]._result)


async def test_tool_cell_arguments_passed_through() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_tool_call("tc-args", "read_file", {"path": "/tmp/foo.py"})
        cell = list(tx.query(ToolCell))[0]
        # Arguments are now actually stored on the cell (the old port
        # dropped them on the floor).
        assert cell._arguments == {"path": "/tmp/foo.py"}


async def test_notice_severities_mount() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_notice("informational", severity="info")
        tx.add_notice("careful with that", severity="warning")
        tx.add_notice("things broke", severity="error")
        notices = list(tx.query(_NoticeCell))
        assert len(notices) == 3
        severities = {n.severity for n in notices}
        assert severities == {"info", "warning", "error"}


async def test_add_system_message_still_works_legacy() -> None:
    """The legacy entry point must keep mounting a cell + recording the
    "System:" substring in _messages so test_tui_wiring.py stays green."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_system_message("legacy path")
        assert any("System:" in m for m in tx._messages)
        # Backed by a _NoticeCell now, severity=info.
        notices = list(tx.query(_NoticeCell))
        assert len(notices) == 1


async def test_assistant_cell_handles_markup_in_buffer() -> None:
    """Stream content that looks like Rich markup must not crash the
    cell (the markdown renderer treats it as literal text)."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.start_assistant_message()
        tx.append_delta("Watch this: [bold]not bold[/] and an [/] orphan tag.")
        tx.finalize_message()
        # Should land in legacy _messages without raising.
        assert any("Assistant:" in m for m in tx._messages)


# ── Approval flow: tool cell state machine ───────────────────────────


async def test_tool_cell_awaiting_then_approved() -> None:
    """Approval-then-execute path leaves a single tool cell in the
    transcript, not a notice-and-result pair."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_tool_call("tc-app", "exec_shell", {"command": "ls"})
        tx.mark_tool_awaiting_approval("tc-app")
        cell = list(tx.query(ToolCell))[0]
        assert cell._status == "awaiting"

        tx.mark_tool_approved("tc-app")
        assert cell._status == "running"

        tx.update_tool_result("tc-app", "drwx file1\n", success=True)
        assert cell._status == "done"
        # No extra notice cells were created.
        from deepseek_tui.tui.widgets.transcript import _NoticeCell
        assert len(list(tx.query(_NoticeCell))) == 0


async def test_tool_cell_denied_terminal() -> None:
    """User denies → cell goes to terminal ``denied`` state and stays
    there even if a follow-up SandboxDeniedEvent updates the reason."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_tool_call("tc-deny", "exec_shell", {"command": "rm -rf /"})
        tx.mark_tool_awaiting_approval("tc-deny")
        tx.mark_tool_denied("tc-deny", "denied")
        # Sandbox follow-up enriches the reason but doesn't reset state.
        tx.mark_tool_denied("tc-deny", "Tool exec_shell denied by approval policy")
        cell = list(tx.query(ToolCell))[0]
        assert cell._status == "denied"
        assert "denied by approval policy" in cell._result
        # Legacy _messages reflects denial.
        assert any("⊘" in m for m in tx._messages)


async def test_approval_dialog_renders_input_summary() -> None:
    """The dialog must actually surface ``input_summary`` so the user
    sees what they're approving."""
    from deepseek_tui.tui.widgets.approval import ApprovalDialog

    class _DialogHarness(App[None]):
        def compose(self) -> ComposeResult:
            yield Transcript()  # filler so the harness has something

    app = _DialogHarness()
    async with app.run_test(size=(100, 30)) as pilot:
        result: list[bool | None] = []
        app.push_screen(
            ApprovalDialog(
                tool_name="exec_shell",
                reason="tool has medium risk level",
                input_summary="rm -rf /tmp/scratch",
                risk_level="medium",
            ),
            lambda r: result.append(r),
        )
        await pilot.pause()
        # Pressing Enter should approve.
        await pilot.press("enter")
        await pilot.pause()
        assert result == [True]


# ── Segment ordering: chronological mount layout ────────────────────


async def test_segments_mount_in_chronological_order() -> None:
    """thinking → tool_call → text deltas must appear in DOM order so
    visible top-to-bottom layout matches the event arrival order.
    Previously ``start_assistant_message`` eagerly mounted an empty
    assistant cell which then attracted tail text deltas, leaving
    tool cards positioned visually *below* the assistant message they
    actually preceded."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_user_message("look at my desktop")
        tx.start_assistant_message()
        tx.append_thinking("I need to list ~/Desktop\n")
        tx.add_tool_call("tc-ls", "exec_shell", {"command": "ls ~/Desktop"})
        tx.update_tool_result("tc-ls", "file1\nfile2\n", success=True)
        tx.append_delta("Here is what I found:\n")
        tx.append_delta("- file1\n- file2")
        tx.finalize_message()

        # Walk through mounted children in DOM order and pluck out the
        # segment cells (ignoring user / divider chrome).
        kinds: list[str] = []
        for w in tx.children:
            name = type(w).__name__
            if name == "_UserCell":
                kinds.append("user")
            elif name == "_ThinkingCell":
                kinds.append("thinking")
            elif name == "ToolCell":
                kinds.append("tool")
            elif name == "_AssistantCell":
                kinds.append("assistant")
        assert kinds == ["user", "thinking", "tool", "assistant"]


async def test_multi_round_thinking_gets_own_segment() -> None:
    """Two thinking bursts separated by a tool call should produce two
    distinct ``_ThinkingCell`` segments (mirrors a multi-round turn
    where the model thinks → calls tool → thinks again → answers)."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.start_assistant_message()
        tx.append_thinking("Round 1 thinking\n")
        tx.add_tool_call("tc-r1", "read_file", {"path": "/x"})
        tx.update_tool_result("tc-r1", "content", success=True)
        tx.append_thinking("Round 2 thinking\n")
        tx.append_delta("Final answer.")
        tx.finalize_message()

        thinking_cells = list(tx.query(_ThinkingCell))
        assert len(thinking_cells) == 2
        assert "Round 1" in thinking_cells[0].content_text
        assert "Round 2" in thinking_cells[1].content_text


def test_summarize_call_args_helper_from_engine() -> None:
    """The engine helper that enriches ApprovalRequest.input_summary
    must pick a useful single-line value."""
    from deepseek_tui.engine.engine import _summarize_call_args

    assert _summarize_call_args({"command": "ls -la"}) == "ls -la"
    assert _summarize_call_args({"empty": "", "path": "/tmp/a"}) == "/tmp/a"
    assert _summarize_call_args(None) == ""
    assert _summarize_call_args({}) == ""
    # Multiline → first line only.
    assert (
        _summarize_call_args({"text": "first\nsecond\nthird"}) == "first"
    )
    # Length cap.
    summary = _summarize_call_args({"v": "x" * 500})
    assert len(summary) <= 200
    assert summary.endswith("…")
