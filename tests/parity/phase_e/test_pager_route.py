"""ToolCell → PagerScreen route integration tests (HANDOVER §pager.2026-05-14).

Until 2026-05-14, ``PagerScreen`` was orphaned: defined in
``widgets/pager.py`` with full vim key handling + a separate
``PagerState`` unit test suite, but nothing ever called
``app.push_screen(PagerScreen(...))``. The fix wires ``ToolCell`` to
push the pager on the ``o`` key.
"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from deepseek_tui.tui.widgets.pager import PagerScreen
from deepseek_tui.tui.widgets.tool_cell import ToolCell


def test_toolcell_has_pager_binding() -> None:
    """``o`` binding must exist on ToolCell and dispatch ``open_pager``."""
    keys = [b.key for b in ToolCell.BINDINGS]
    assert "o" in keys
    o_binding = next(b for b in ToolCell.BINDINGS if b.key == "o")
    assert o_binding.action == "open_pager"


def test_toolcell_is_focusable() -> None:
    """Bindings on Static fire only when the widget is focusable."""
    assert ToolCell.can_focus is True


def _make_host(cell: ToolCell) -> type[App[None]]:
    class _Host(App[None]):
        def compose(self) -> ComposeResult:
            yield cell

    return _Host


@pytest.mark.asyncio
async def test_open_pager_action_pushes_screen_when_result_set() -> None:
    """After ``set_result`` runs, pressing ``o`` should push a PagerScreen."""
    cell = ToolCell("read_file", "call_1", arguments={"path": "src/x.py"})
    cell.set_result(
        "\n".join(f"line {i}" for i in range(40)),
        success=True,
    )

    async with _make_host(cell)().run_test() as pilot:
        cell.focus()
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()

        # The PagerScreen should now be the top screen of the screen stack.
        top = pilot.app.screen
        assert isinstance(top, PagerScreen), f"top screen is {type(top).__name__}"


@pytest.mark.asyncio
async def test_open_pager_noop_when_no_result() -> None:
    """No result yet (cell still running) → ``o`` must NOT push a screen.

    Opening an empty pager would cover the in-progress cell with a blank
    modal — surprise UI nobody asked for. Guard from ``action_open_pager``.
    """
    cell = ToolCell("read_file", "call_1", arguments={"path": "src/x.py"})
    # Don't call set_result — leave _result empty.

    async with _make_host(cell)().run_test() as pilot:
        cell.focus()
        await pilot.pause()
        screens_before = len(pilot.app.screen_stack)
        await pilot.press("o")
        await pilot.pause()
        screens_after = len(pilot.app.screen_stack)
        assert screens_before == screens_after


@pytest.mark.asyncio
async def test_pager_dismisses_on_q() -> None:
    """PagerScreen's own ``q`` / ``escape`` binding closes the modal."""
    cell = ToolCell("exec_shell", "call_2", arguments={"command": "ls"})
    cell.set_result("\n".join(f"file{i}" for i in range(40)), success=True)

    async with _make_host(cell)().run_test() as pilot:
        cell.focus()
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(pilot.app.screen, PagerScreen)

        # Drive the pager via its own action — this is the binding path
        # the framework would take if the user pressed ``q``. Going through
        # ``run_action`` makes the test resilient to how Textual delivers
        # the key to the modal (focus quirks across versions).
        await pilot.app.screen.run_action("key('q')")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, PagerScreen)
