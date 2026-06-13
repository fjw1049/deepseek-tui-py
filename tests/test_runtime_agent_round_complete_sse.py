"""SSE serialization covers internal engine events."""

from __future__ import annotations

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.runtime import engine_event_to_sse


def test_agent_round_complete_event_serializes() -> None:
    payload = engine_event_to_sse(
        AgentRoundCompleteEvent(
            round_idx=1,
            tool_calls=(ToolCall(id="t1", name="read_file", arguments={"path": "a.py"}),),
        )
    )
    assert payload["event"] == "agent_round_complete"
    assert payload["round_idx"] == 1
    assert payload["terminal"] is False


def test_terminal_agent_round_complete_event() -> None:
    payload = engine_event_to_sse(AgentRoundCompleteEvent(round_idx=2))
    assert payload["terminal"] is True
