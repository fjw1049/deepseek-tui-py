"""Offline baseline for context audit; assertions document pre-fix behavior."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from deepseek_tui.engine.capacity import _create_summary, plan_compaction, prune_old_tool_results
from deepseek_tui.engine.context_pressure import (
    format_user_requests_block,
    parse_user_requests_block,
)
from deepseek_tui.engine.cycle import CycleConfig, StructuredState
from deepseek_tui.engine.orchestrator.maintenance import SessionMaintenanceMixin
from deepseek_tui.protocol.messages import Message, MessageOrigin, Role, ToolUseBlock
from deepseek_tui.protocol.responses import StreamError, StreamTextDelta
from deepseek_tui.tools.registry import ToolContext


async def main(root):
    class BrokenStream:
        async def stream_chat_completion(self, request):
            yield StreamTextDelta(
                text="### Goal\nKeep all facts.\n### Next step\nFinish the remaining checks."
            )
            yield StreamError(message="connection lost", retryable=False)

    summary = await _create_summary(BrokenStream(), [Message.user("request")], "deepseek-chat")
    assert "Next step" in summary
    messages = [
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="call", name="read_file", input={})]),
        Message.tool_result("call", "pinned result"),
    ]
    messages += [Message.user(f"turn {i}") for i in range(10)]
    plan = plan_compaction(messages, {1}, keep_recent_tokens=0)
    assert 1 in plan.pinned_indices and 0 not in plan.pinned_indices

    history = [Message.tool_result("call", "important fresh output")]
    history += [
        Message.user("runtime reminder", origin=MessageOrigin.SYSTEM_REMINDER) for _ in range(15)
    ]
    prune_old_tool_results(history)
    assert "omitted" in history[0].content[0].content

    engine = SimpleNamespace(
        last_real_input_tokens=10**9,
        last_real_input_estimate=0,
        cycle_config=CycleConfig(),
        _cycle_session_id="context-probe",
        _cycle_n=0,
        _cycle_started_at=0,
        tool_context=ToolContext(working_directory=root),
        _cycle_structured_state=lambda: StructuredState(),
        client=Mock(),
        mode="agent",
    )
    cycle_messages = [Message.user(f"message {i}") for i in range(30)]
    producer = AsyncMock(return_value="usable briefing")
    with patch("deepseek_tui.engine.cycle.produce_briefing", producer):
        await SessionMaintenanceMixin._maybe_advance_cycle(engine, cycle_messages, "deepseek-chat")
    assert producer.await_count == 0 and engine._cycle_n == 1

    request = "Preserve </prior_user_requests> this exact constraint"
    replay = parse_user_requests_block(format_user_requests_block([request]))
    assert replay != [request]
    print(
        json.dumps(
            {
                "summary_after_stream_error": summary,
                "pinned_result_has_parent": 0 in plan.pinned_indices,
                "fresh_result_after_15_synthetic_messages": history[0].content[0].content,
                "cycle_briefing_calls": producer.await_count,
                "cycle_advanced_despite_no_briefing": engine._cycle_n,
                "request_tag_roundtrip": replay,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="context-audit-") as tmp:
        os.environ["DEEPSEEK_HOME"] = tmp
        asyncio.run(main(Path(tmp)))
