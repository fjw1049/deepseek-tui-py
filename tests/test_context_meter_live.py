"""The context meter must measure the working turn, not the persisted transcript."""

from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.context import estimate_context_breakdown
from deepseek_tui.engine.handle import EngineHandle, SendMessageOp
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.turn import TurnResult
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.registry import ToolContext, ToolRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("raise_error", [False, True])
async def test_meter_uses_live_messages_and_releases_them(tmp_path, monkeypatch, raise_error):
    engine = Engine(
        handle=EngineHandle(),
        client=object(),
        tool_registry=ToolRegistry(),
        tool_context=ToolContext(working_directory=tmp_path),
    )
    monkeypatch.setattr(engine, "_save_crash_checkpoint", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "_finish_goal_turn", AsyncMock())
    monkeypatch.setattr(engine, "_take_git_snapshot_message", lambda: None)
    monkeypatch.setattr(engine, "_take_handoff_reminder_message", lambda: None)

    async def run(**kwargs):
        messages = kwargs["messages"]
        messages.append(Message.user("large tool result " * 20_000))
        baseline = estimate_context_breakdown(
            model="deepseek-chat",
            messages=messages,
            workspace=tmp_path,
            api_tools=[],
            auto_approve=False,
        )
        # A provider can tokenize substantially more efficiently than the local estimator.
        engine.last_real_input_tokens = baseline["total"] // 2
        engine.last_real_input_estimate = baseline["total"]
        for breakdown in (engine.context_breakdown(), await engine.context_breakdown_live()):
            assert breakdown["total"] == engine.last_real_input_tokens
            assert breakdown["conversation"] > 0
        if raise_error:
            raise RuntimeError("stream failed")
        return TurnResult(assistant_message=None, cancelled=True)

    monkeypatch.setattr(engine, "_run_conversation", run)
    if raise_error:
        with pytest.raises(RuntimeError, match="stream failed"):
            await engine._handle_send_message_inner(SendMessageOp(content="hello"), "test-turn")
    else:
        await engine._handle_send_message_inner(SendMessageOp(content="hello"), "test-turn")
    assert engine._active_context_messages is None
    assert engine.session_messages == []
    assert engine.context_breakdown()["total"] > 0
