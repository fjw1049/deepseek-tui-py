"""Regression: external content must not be parsed as Rich markup.

A grep result that contained the literal ``[/]`` token (the closing tag
of a ``[dim]...[/]`` span found in a log preview the model had searched)
crashed the whole transcript worker with ``MarkupError`` and froze the
session. The fix is to run every interpolation site through
``rich.markup.escape``; these tests pin that contract.

Reproduction in the original bug:
  grep_files pattern='filter' over .deepseek/logs/deepseek.log
  → ToolResult.content contains "...preview='帮我看看...[/]"
  → ToolCell._refresh built f"[dim]{preview}[/]"
  → Static.update parsed it as markup, hit unbalanced "[/]", raised.
"""
from __future__ import annotations

from textual.app import App, ComposeResult

from deepseek_tui.tui.widgets.tool_cell import ToolCell
from deepseek_tui.tui.widgets.transcript import Transcript


class _Harness(App[None]):
    def compose(self) -> ComposeResult:
        yield Transcript()
        yield ToolCell("grep_files", "call_0")


_POISONED_RESULT = (
    ".deepseek/logs/deepseek.log:2953:2026-05-11T...] composer_submit "
    "text_len=35 preview='帮我看看桌面上有没有关于filt...[/]"
)


# --- ToolCell --------------------------------------------------------------


async def test_tool_cell_does_not_crash_on_markup_in_result() -> None:
    """Setting a result that contains ``[/]`` must not raise."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        cell = app.query_one(ToolCell)
        # If escape is missing this raises MarkupError before returning.
        cell.set_result(_POISONED_RESULT, success=True)
        # Data is preserved verbatim on the cell (we only escape for render).
        assert "deepseek.log" in cell._result
        assert cell._status == "done"


async def test_tool_cell_handles_bracket_tool_name() -> None:
    """Defensive: tool_name with brackets should also not break rendering."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        weird = ToolCell("not-a-real[tool]", "call_1")
        await app.mount(weird)
        weird.set_result("ok", success=True)
        assert weird.tool_name == "not-a-real[tool]"


# --- Transcript cells ------------------------------------------------------


async def test_transcript_user_message_escapes_markup() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        # Common real-world payloads: pasted code, error tracebacks with
        # "[stderr]" prefixes, log lines.
        tx.add_user_message("paste this: [bold]not bold[/] and [/] alone")


async def test_transcript_system_message_escapes_markup() -> None:
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.add_system_message("Error: shell stderr → [/] orphan close-tag")


async def test_transcript_assistant_delta_escapes_markup() -> None:
    """Streaming chunks that happen to contain ``[..]`` shouldn't break."""
    app = _Harness()
    async with app.run_test(size=(80, 24)):
        tx = app.query_one(Transcript)
        tx.start_assistant_message()
        tx.append_delta("Here is some markdown: [link](http://x) and an [/] tag.")
        tx.finalize_message()
