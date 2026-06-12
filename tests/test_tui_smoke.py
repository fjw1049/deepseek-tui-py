"""Minimal TUI wiring smoke — catches import/wiring regressions on the main submit path."""

from __future__ import annotations

import inspect

import deepseek_tui.tui.app as tui_app
from deepseek_tui.engine.handle import SendMessageOp


def test_send_message_op_imported_in_tui_app() -> None:
    """Non-steer composer submit must resolve SendMessageOp (regression guard)."""
    assert hasattr(tui_app, "SendMessageOp")
    assert tui_app.SendMessageOp is SendMessageOp


def test_submit_user_message_uses_send_message_op() -> None:
    from deepseek_tui.tui.app import DeepSeekTUI

    source = inspect.getsource(DeepSeekTUI._submit_user_message)
    assert "SendMessageOp" in source
    assert "send_op" in source


def test_user_input_handler_uses_contract_answer_shape() -> None:
    from deepseek_tui.tui.app import DeepSeekTUI

    source = inspect.getsource(DeepSeekTUI._handle_user_input_event)
    assert '"answers"' in source
    assert "question_id" in source


def test_transcript_hydrate_from_messages_exists() -> None:
    from deepseek_tui.tui.transcript import Transcript

    assert hasattr(Transcript, "hydrate_from_messages")
