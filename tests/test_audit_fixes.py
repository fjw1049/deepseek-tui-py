"""Regression tests for audit-driven fixes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deepseek_tui.protocol.messages import Message, TextBlock
from deepseek_tui.state.checkpoint import clear_checkpoint, save_checkpoint
from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.patch_engine import (
    FilePatch,
    Hunk,
    HunkLine,
    HunkLineKind,
)
from deepseek_tui.tools.utility_tools import (
    ApplyPatchTool,
    _apply_changes,
    _apply_file_patches,
)
from deepseek_tui.tui.session_restore import (
    apply_messages_to_engine,
    try_restore_crash_checkpoint,
)


def _tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(working_directory=tmp_path, metadata={})


def test_apply_messages_to_engine_replaces_list() -> None:
    engine = SimpleNamespace(session_messages=[Message(role="user", content=[])])
    restored = [
        Message(role="user", content=[TextBlock(type="text", text="hello")]),
    ]
    apply_messages_to_engine(engine, restored)
    assert engine.session_messages is not restored
    assert len(engine.session_messages) == 1
    assert engine.session_messages[0].content[0].text == "hello"  # type: ignore[attr-defined]


def test_try_restore_crash_checkpoint() -> None:
    clear_checkpoint()
    save_checkpoint(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "recovered"}],
                }
            ],
            "turn_counter": 3,
            "model": "deepseek-chat",
            "metadata": {"id": "sess-abc"},
        }
    )
    engine = SimpleNamespace(session_messages=[], turn_counter=0, default_model="x")
    result = try_restore_crash_checkpoint(engine)
    assert result is not None
    messages, metadata = result
    assert len(messages) == 1
    assert metadata["id"] == "sess-abc"
    assert engine.turn_counter == 3
    assert engine.default_model == "deepseek-chat"
    clear_checkpoint()


def test_apply_file_patches_rolls_back_on_failure(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    context = _tool_context(tmp_path)

    first_patch = FilePatch(
        path="a.txt",
        hunks=[
            Hunk(
                old_start=1,
                old_count=1,
                new_start=1,
                new_count=1,
                lines=[
                    HunkLine(kind=HunkLineKind.CONTEXT, content="alpha"),
                    HunkLine(kind=HunkLineKind.REMOVE, content="alpha"),
                    HunkLine(kind=HunkLineKind.ADD, content="ALPHA"),
                ],
            )
        ],
    )
    bad_hunk = Hunk(
        old_start=99,
        old_count=1,
        new_start=99,
        new_count=1,
        lines=[HunkLine(kind=HunkLineKind.REMOVE, content="missing")],
    )
    second_patch = FilePatch(path="b.txt", hunks=[bad_hunk])

    with pytest.raises(ToolError):
        _apply_file_patches([first_patch, second_patch], context, fuzz=0)

    assert first.read_text(encoding="utf-8") == "alpha\n"
    assert second.read_text(encoding="utf-8") == "beta\n"


def test_apply_changes_rolls_back_on_failure(tmp_path: Path) -> None:
    path = tmp_path / "only.txt"
    path.write_text("before\n", encoding="utf-8")
    context = _tool_context(tmp_path)
    changes = [
        {"path": "only.txt", "content": "after\n"},
        {"path": "", "content": "bad"},
    ]
    with pytest.raises(ToolError):
        _apply_changes(changes, context)
    assert path.read_text(encoding="utf-8") == "before\n"


@pytest.mark.asyncio
async def test_apply_patch_tool_end_to_end(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("line one\nline two\n", encoding="utf-8")
    patch = (
        "--- a/file.txt\n"
        "+++ b/file.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " line one\n"
        "-line two\n"
        "+line TWO\n"
    )
    tool = ApplyPatchTool()
    context = _tool_context(tmp_path)
    result = await tool.execute({"patch": patch}, context)
    assert result.success
    assert "line TWO" in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_action_quit_awaits_cancelled_engine_task() -> None:
    from deepseek_tui.tui.app import DeepSeekTUI

    app = DeepSeekTUI(config=MagicMock())
    app._engine = None

    async def _slow_run() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise

    app._engine_task = asyncio.create_task(_slow_run())
    with patch.object(app, "exit") as mock_exit:
        await app.action_quit()
    assert app._engine_task.done()
    mock_exit.assert_called_once()
