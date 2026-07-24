"""Regression tests for audit-driven fixes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deepseek_tui.protocol.messages import Message, TextBlock
from deepseek_tui.state.session import clear_checkpoint, save_checkpoint
from deepseek_tui.tui.session_restore import (
    apply_messages_to_engine,
    try_restore_crash_checkpoint,
)


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
