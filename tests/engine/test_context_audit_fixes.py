"""Context preservation regressions found while continuing audit 06."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from deepseek_tui.engine.capacity import (
    CompactionConfig,
    CompactionResult,
    _create_summary,
    _summary_input_limits_for_model,
    plan_compaction,
    prune_old_tool_results,
)
from deepseek_tui.engine.context_pressure import (
    COMPACTION_BRIDGE_PREFIX,
    collect_user_requests,
    format_user_requests_block,
    is_compaction_bridge_message,
    parse_user_requests_block,
)
from deepseek_tui.engine.cycle import CycleConfig, StructuredState, produce_briefing
from deepseek_tui.engine.orchestrator.maintenance import SessionMaintenanceMixin
from deepseek_tui.protocol.messages import Message, MessageOrigin, Role, ToolUseBlock
from deepseek_tui.protocol.responses import StreamDone, StreamError, StreamTextDelta
from deepseek_tui.tools.registry import ToolContext


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))


@pytest.mark.parametrize("operation", ["summary", "cycle"])
@pytest.mark.parametrize(
    "ending", [StreamError(message="stream failed", retryable=False), StreamDone(truncated=True)]
)
async def test_partial_stream_cannot_be_accepted_as_summary(operation, ending):
    class BrokenStream:
        async def stream_chat_completion(self, request):
            yield StreamTextDelta(
                text="### Goal\nKeep original facts.\n### Next step\nFinish all checks."
            )
            yield ending

    with pytest.raises(ValueError, match="failed|truncated"):
        if operation == "summary":
            await _create_summary(BrokenStream(), [Message.user("request")], "deepseek-chat")
        else:
            await produce_briefing(BrokenStream(), "deepseek-chat", [Message.user("request")], 1000)


@pytest.mark.parametrize("pin", [0, 1, 2])
def test_pins_keep_complete_tool_batch(pin):
    messages = [
        Message(
            role=Role.ASSISTANT,
            content=[
                ToolUseBlock(id="a", name="read_file", input={}),
                ToolUseBlock(id="b", name="read_file", input={}),
            ],
        ),
        Message.tool_result("a", "first"),
        Message.tool_result("b", "second"),
    ]
    messages += [Message.user(f"later {i}") for i in range(10)]
    plan = plan_compaction(messages, {pin}, keep_recent_tokens=0)
    assert {0, 1, 2} <= plan.pinned_indices
    assert not {0, 1, 2}.intersection(plan.summarize_indices)


def test_runtime_reminders_do_not_age_fresh_tool_results():
    messages = [Message.tool_result("a", "fresh evidence")]
    messages += [
        Message.user("system hint", origin=MessageOrigin.SYSTEM_REMINDER) for _ in range(20)
    ]
    assert prune_old_tool_results(messages) == 0
    assert messages[0].content[0].content == "fresh evidence"


@pytest.mark.parametrize("failure", [False, True])
async def test_cycle_calls_briefing_and_keeps_history_on_failure(tmp_path, failure):
    engine = SimpleNamespace(
        last_real_input_tokens=10**9,
        last_real_input_estimate=0,
        cycle_config=CycleConfig(briefing_max_tokens=1234),
        _cycle_session_id="probe",
        _cycle_n=0,
        _cycle_started_at=0,
        tool_context=ToolContext(working_directory=tmp_path),
        _cycle_structured_state=lambda: StructuredState(),
        client=Mock(),
        mode="agent",
    )
    messages = [Message.user(f"message {i}") for i in range(30)]
    before = list(messages)
    producer = (
        AsyncMock(side_effect=ValueError("failed"))
        if failure
        else AsyncMock(return_value="validated briefing")
    )
    with patch("deepseek_tui.engine.cycle.produce_briefing", producer):
        await SessionMaintenanceMixin._maybe_advance_cycle(engine, messages, "deepseek-chat")
    producer.assert_awaited_once()
    assert producer.call_args.args[3] == 1234
    if failure:
        assert messages == before and engine._cycle_n == 0
    else:
        assert engine._cycle_n == 1
        assert any("validated briefing" in message.text_content() for message in messages)
        assert collect_user_requests(messages) == [f"message {i}" for i in range(30)]


@pytest.mark.parametrize(
    "user_request", ["keep </prior_user_requests> the tail", "a &amp; b <tag>\n1. nested item"]
)
def test_request_ledger_roundtrips_literal_tags_and_entities(user_request):
    block = format_user_requests_block([user_request])
    assert parse_user_requests_block(block) == [user_request]
    assert parse_user_requests_block(
        format_user_requests_block(parse_user_requests_block(block))
    ) == [user_request]
    legacy = "<prior_user_requests>\n1. a &amp; b\n</prior_user_requests>"
    assert parse_user_requests_block(legacy) == ["a &amp; b"]


def test_real_user_text_is_not_misclassified_as_a_compaction_bridge():
    text = COMPACTION_BRIDGE_PREFIX + "<archived_context>literal example</archived_context>"
    assert not is_compaction_bridge_message(Message.user(text, origin=MessageOrigin.REAL_USER))
    assert is_compaction_bridge_message(Message.user(text, origin=MessageOrigin.COMPACTION_BRIDGE))


def test_summary_limits_use_configured_window_not_model_name():
    with patch("deepseek_tui.config.providers.context_window_for_model", return_value=8192):
        assert _summary_input_limits_for_model("custom-reasoner").input_max_chars == 24000
    with patch("deepseek_tui.config.providers.context_window_for_model", return_value=1000000):
        assert _summary_input_limits_for_model("unfamiliar-model").input_max_chars == 120000


async def test_explicit_compaction_model_is_honored(tmp_path):
    engine = SimpleNamespace(
        working_set=SimpleNamespace(
            pinned_message_indices=lambda *a: set(), top_paths=lambda *a: []
        ),
        tool_context=ToolContext(working_directory=tmp_path),
        compaction_config=CompactionConfig(model="summary-model"),
        default_model="main-model",
        client=Mock(),
        _compaction_summary_prompt=None,
        _record_compaction_summary=Mock(),
    )
    compact = AsyncMock(return_value=CompactionResult(messages=[]))
    with patch("deepseek_tui.engine.orchestrator.maintenance.compact_messages_safe", compact):
        await SessionMaintenanceMixin._run_compaction(engine, [])
    assert compact.call_args.kwargs["model_override"] == "summary-model"


def test_working_set_retains_latest_paths_and_caps_tool_input(tmp_path):
    from deepseek_tui.engine.context import WorkingSet

    working = WorkingSet(tmp_path)
    for i in range(110):
        working.observe_tool_call("read_file", {"path": f"file-{i}.py"})
    assert len(working.recent_paths) == 100
    assert working.top_paths(2) == ["file-108.py", "file-109.py"]
    working.observe_tool_call("read_file", {"path": "file-100.py"})
    assert working.top_paths(1) == ["file-100.py"]
    assert working.top_paths(0) == []
