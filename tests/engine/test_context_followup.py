"""Capacity rejection and lifecycle regressions for the second context audit pass."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine import capacity, prompts
from deepseek_tui.engine.capacity import CompactionConfig, CompactionBudgetError
from deepseek_tui.engine.context import estimate_tokens
from deepseek_tui.engine.context_pressure import measure_context_pressure
from deepseek_tui.engine.cycle import enforce_briefing_cap
from deepseek_tui.protocol.messages import Message, MessageRequest


def test_date_refreshes_across_midnight(monkeypatch):
    class Clock:
        value = datetime(2026, 9, 27, 23, 59)

        @classmethod
        def now(cls):
            return cls.value

    monkeypatch.setattr(prompts, "datetime", Clock)
    assert prompts.process_today() == "2026-09-27"
    Clock.value = datetime(2026, 9, 28)
    assert prompts.process_today() == "2026-09-28"


@pytest.mark.parametrize("text", ["中文压缩摘要。" * 1000, "a complicated handoff " * 1000])
def test_briefing_cap_counts_marker_and_cjk(text):
    output = enforce_briefing_cap(text, 80)
    assert estimate_tokens(output) <= 80
    assert "truncated" in output
    assert enforce_briefing_cap(text, -1) == ""


def test_unpaired_measurement_does_not_hide_growth():
    pressure = measure_context_pressure(
        "deepseek-chat", [Message.user("新的长请求" * 1000)], real_input_tokens=10
    )
    assert pressure.tokens > 10


def test_summary_budget_includes_system_and_output(monkeypatch):
    monkeypatch.setattr("deepseek_tui.config.providers.context_window_for_model", lambda _: 100)
    request = MessageRequest(
        model="tiny", messages=[Message.user("hi")], system_prompt="说明" * 1000, max_tokens=90
    )
    with pytest.raises(CompactionBudgetError):
        capacity.validate_summary_request_budget(request)


async def test_oversize_previous_summary_never_calls_provider(monkeypatch):
    monkeypatch.setattr("deepseek_tui.config.providers.context_window_for_model", lambda _: 4096)
    client = SimpleNamespace(stream_chat_completion=AsyncMock())
    with pytest.raises(CompactionBudgetError):
        await capacity._create_summary(
            client, [Message.user("hello")], "tiny", previous_summary="中文" * 10000
        )
    client.stream_chat_completion.assert_not_called()


@pytest.mark.parametrize("oversize", [False, True])
async def test_rejected_candidate_preserves_original_history(monkeypatch, oversize):
    messages = (
        [Message.user("original request " + str(i)) for i in range(12)]
        if oversize
        else [Message.assistant("previous work " * 1000) for _ in range(12)]
    )
    summary = (
        "### Goal\n"
        + (
            "巨大" * 2000
            if oversize
            else "Finish the requested changes and retain all current requirements."
        )
        + "\n### Next step\nContinue"
    )
    create = AsyncMock(return_value=summary)
    monkeypatch.setattr(capacity, "_create_summary", create)
    monkeypatch.setattr(
        "deepseek_tui.config.providers.context_window_for_model",
        lambda _: 100 if not oversize else 100000,
    )
    result = await capacity.compact_messages_safe(
        SimpleNamespace(),
        messages,
        CompactionConfig(keep_recent_tokens=0),
        system_prompt="系统" * 500,
        output_reserve=100,
    )
    assert not result.success
    assert result.messages is messages
    assert result.failure_reason
    assert ("does not reduce" if oversize else "Retained context") in result.failure_reason
    create.assert_awaited_once()


async def test_reduced_candidate_commits(monkeypatch):
    messages = [Message.user(("old history " * 1000) + str(i)) for i in range(12)]
    monkeypatch.setattr(
        capacity,
        "_create_summary",
        AsyncMock(
            return_value="### Goal\nFinish the requested implementation.\n### Next step\nRun the relevant tests and review the resulting changes."
        ),
    )
    result = await capacity.compact_messages_safe(
        SimpleNamespace(), messages, CompactionConfig(keep_recent_tokens=0)
    )
    assert result.success
    assert result.removed_messages


def test_route_change_invalidates_measurement():
    from unittest.mock import Mock
    from deepseek_tui.engine import Engine
    from deepseek_tui.engine.usage_ledger import TurnUsageLedger
    from deepseek_tui.config.models import Config

    engine = Engine.__new__(Engine)
    engine.turn_usage_ledger = TurnUsageLedger()
    engine.turn_loop = SimpleNamespace(client=None)
    engine.tool_context = SimpleNamespace(metadata={}, subagent_manager=None)
    engine.last_real_input_tokens = 99999
    engine.last_real_input_estimate = 55555
    engine.set_model_route(Mock(), Config(), "replacement-model")
    assert engine.last_real_input_tokens == engine.last_real_input_estimate == 0


async def test_cycle_oversize_request_is_rejected_before_provider(monkeypatch):
    from deepseek_tui.engine.cycle import produce_briefing

    monkeypatch.setattr("deepseek_tui.config.providers.context_window_for_model", lambda _: 100)
    client = SimpleNamespace(stream_chat_completion=AsyncMock())
    with pytest.raises(CompactionBudgetError):
        await produce_briefing(client, "tiny", [Message.user("history")], 1000)
    client.stream_chat_completion.assert_not_called()


async def test_all_pinned_history_has_actionable_reason():
    messages = [Message.user(str(i)) for i in range(12)]
    client = SimpleNamespace(stream_chat_completion=AsyncMock())
    result = await capacity.compact_messages_safe(
        client, messages, CompactionConfig(keep_recent_tokens=0),
        pinned_indices=set(range(len(messages))),
    )
    assert result.messages is messages
    assert "retained" in result.failure_reason
    client.stream_chat_completion.assert_not_called()
