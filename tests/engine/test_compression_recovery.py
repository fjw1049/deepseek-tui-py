"""Regression cases for failed compression and request-shaped overflow recovery."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from deepseek_tui.config.models import Config, ContextConfig, FeatureConfig
from deepseek_tui.engine import Engine, capacity, interventions
from deepseek_tui.engine.context import WorkingSet
from deepseek_tui.engine.context_pressure import (
    build_compaction_bridge_text,
    prepend_compaction_bridge,
)
from deepseek_tui.engine.cycle import produce_briefing
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator.maintenance import SessionMaintenanceMixin
from deepseek_tui.engine.turn import TurnLoop, TurnOutcomeStatus
from deepseek_tui.protocol.messages import Message, MessageRequest, ThinkingBlock
from deepseek_tui.protocol.responses import StreamDone, StreamError, StreamTextDelta
from deepseek_tui.tools.registry import ToolContext
from tests.engine.test_append_summary import single_user_history

SUMMARY = (
    "### Goal\nPreserve config.toml and finish the investigation.\n### Next step\nVerify results."
)


@pytest.mark.parametrize("operation", ["summary", "cycle"])
async def test_summary_copies_effective_request_including_thinking_off(operation):
    from deepseek_tui.client.deepseek import DeepSeekClient

    messages = [Message.user("Keep config.toml unchanged"), Message.assistant("observed")]
    messages[-1].content.insert(0, ThinkingBlock(thinking="private reasoning"))
    request = MessageRequest(
        model="deepseek-flash",
        messages=messages,
        system_prompt="stable system",
        tools=[
            {
                "type": "function",
                "function": {"name": "read_file", "parameters": {"type": "object"}},
            }
        ],
        tool_choice={"type": "auto"},
        reasoning_effort="off",
        temperature=0.3,
        top_p=0.8,
        extra_body={"frequency_penalty": 0.1},
        max_tokens=1024,
    )
    captured = []

    async def stream(value):
        captured.append(value)
        yield StreamTextDelta(text=SUMMARY)

    client = SimpleNamespace(stream_chat_completion=stream)
    if operation == "summary":
        await capacity._create_summary(client, messages, request.model, request_template=request)
    else:
        await produce_briefing(client, request.model, messages, 3000, request_template=request)
    native = DeepSeekClient(api_key="offline-test")
    try:
        main = native._build_payload(request)
        summary = native._build_payload(captured[0])
    finally:
        await native.close()
    assert summary["messages"][:-1] == main["messages"]
    assert "reasoning_content" not in summary["messages"][-2]
    for key in main.keys() - {"messages", "max_tokens"}:
        assert summary[key] == main[key]
    assert request.max_tokens == 1024
    assert captured[0].max_tokens <= 8192


async def test_working_file_references_cannot_block_summary(tmp_path):
    messages = single_user_history()
    working = WorkingSet(tmp_path)
    working.observe_tool_call("read_file", {"path": "x"})
    assert working.pinned_message_indices(messages, tmp_path)
    calls = []

    async def stream(request):
        calls.append(request)
        yield StreamTextDelta(text=SUMMARY)

    engine = SimpleNamespace(
        working_set=working,
        tool_context=ToolContext(working_directory=tmp_path),
        compaction_config=capacity.CompactionConfig(keep_recent_tokens=0, max_input_tokens=100),
        client=SimpleNamespace(stream_chat_completion=stream),
        default_model="deepseek-flash",
        _compaction_summary_prompt=None,
        _record_compaction_summary=Mock(),
        mode="agent",
    )
    assert capacity.should_compact(messages, engine.compaction_config, model=engine.default_model)
    result = await SessionMaintenanceMixin._run_compaction(engine, messages)
    assert result.success, result.failure_reason
    assert result.model_calls == len(calls) == 1
    assert calls[0].messages[:-1] == messages
    assert any("keep config.toml unchanged" in m.text_content() for m in result.messages)


def test_previous_bridge_does_not_count_toward_summarizable_messages():
    messages = prepend_compaction_bridge(
        [Message.assistant("history " * 100) for _ in range(9)],
        build_compaction_bridge_text(SUMMARY),
    )
    assert not capacity.should_compact(
        messages,
        capacity.CompactionConfig(keep_recent_tokens=0, max_input_tokens=1),
    )


async def test_overflow_budget_rejection_falls_back_without_calling_model(monkeypatch):
    monkeypatch.setattr("deepseek_tui.config.providers.context_window_for_model", lambda _: 8192)
    messages = single_user_history()
    original = [m.model_dump() for m in messages]
    client = SimpleNamespace(stream_chat_completion=Mock())
    request = MessageRequest(
        model="tiny", messages=messages, system_prompt="stable", max_tokens=512
    )
    records = []
    monkeypatch.setattr(interventions, "record", lambda *args, **kwargs: records.append(kwargs))

    async def compact(history, **kwargs):
        return await capacity.compact_messages_safe(
            client,
            history,
            capacity.CompactionConfig(keep_recent_tokens=0),
            model_override=kwargs.pop("model"),
            **kwargs,
        )

    result, _ = await SessionMaintenanceMixin._emergency_compact(
        SimpleNamespace(_run_compaction=compact),
        request,
    )
    client.stream_chat_completion.assert_not_called()
    assert [m.model_dump() for m in messages] == original
    assert [m.model_dump() for m in result[-4:]] == original[-4:]
    assert result[0] == messages[0]
    assert sum(map(capacity._estimate_tokens_for_message, result)) < sum(
        map(capacity._estimate_tokens_for_message, messages)
    )
    assert records[0]["outcome"] == "pruned"
    assert "exceeds estimated context budget" in records[0]["failure_reason"]
    assert records[0]["model_calls"] == 0


async def test_provider_overflow_passes_effective_request_to_recovery():
    requests = []
    recovered = []

    async def stream(request):
        requests.append(request.model_copy(deep=True))
        if len(requests) == 1:
            yield StreamError(message="maximum context length exceeded", retryable=False)
        else:
            yield StreamTextDelta(text="done")
            yield StreamDone()

    async def compact(request):
        recovered.append(request.model_copy(deep=True))
        return [Message.user("short preserved constraint")]

    request = MessageRequest(
        model="deepseek-flash",
        messages=[Message.user("history " * 100)],
        system_prompt="stable",
        reasoning_effort="off",
        top_p=0.9,
        extra_body={"frequency_penalty": 0.1},
    )
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    result = await TurnLoop(
        SimpleNamespace(stream_with_retry=stream),
        compact_request_fn=compact,
    ).run(request, AsyncMock(), asyncio.Event(), tools=tools)
    assert result.outcome is TurnOutcomeStatus.SUCCESS
    assert recovered[0] == requests[0]
    assert recovered[0].tools == tools
    assert requests[1].messages == [Message.user("short preserved constraint")]


async def test_context_caps_are_validated_and_wired(tmp_path):
    with pytest.raises(ValidationError):
        ContextConfig(max_input_tokens=0)
    config = Config(
        context=ContextConfig(max_input_tokens=30000, cycle_max_input_tokens=45000),
        features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False),
    )
    engine = await Engine.create(
        handle=EngineHandle(),
        client=AsyncMock(),
        config=config,
        working_directory=tmp_path,
        start_mcp=False,
    )
    try:
        assert engine.compaction_config.max_input_tokens == 30000
        assert engine.cycle_config.max_input_tokens == 45000
    finally:
        await engine.shutdown_session()


async def test_truncation_at_eight_k_does_not_spend_on_identical_retry():
    calls = []

    async def stream(request):
        calls.append(request)
        yield StreamTextDelta(text=SUMMARY)
        yield StreamDone(truncated=True)

    messages = single_user_history()
    result = await capacity.compact_messages_safe(
        SimpleNamespace(stream_chat_completion=stream),
        messages,
        capacity.CompactionConfig(keep_recent_tokens=0, model="deepseek-flash"),
    )
    assert not result.success
    assert result.messages is messages
    assert result.model_calls == len(calls) == 1
    assert calls[0].max_tokens == 8192
    assert "truncated" in result.failure_reason


async def test_engine_sends_compacted_history_and_matching_request_controls(tmp_path):
    from tests.engine.test_browser_primary_loop import ScriptedClient

    client = ScriptedClient([SUMMARY, "Investigation complete."])
    engine = await Engine.create(
        handle=EngineHandle(),
        client=client,
        working_directory=tmp_path,
        config=Config(
            reasoning_effort="off",
            cycle_enabled=False,
            context=ContextConfig(max_input_tokens=100),
            features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False),
        ),
        start_mcp=False,
    )
    engine.compaction_config.keep_recent_tokens = 0
    engine.working_set.observe_tool_call("read_file", {"path": "x"})
    messages = single_user_history()
    original = [m.model_dump() for m in messages]
    try:
        await engine._run_conversation(messages, "deepseek-flash", "stable", None)
        summary_request, task_request = client.requests
        assert [m.model_dump() for m in summary_request.messages[:-1]] == original
        assert len(task_request.messages) < len(original)
        assert "<archived_context>" in task_request.messages[0].text_content()
        for field in (
            "system_prompt",
            "tools",
            "tool_choice",
            "reasoning_effort",
            "temperature",
            "top_p",
            "extra_body",
        ):
            assert getattr(summary_request, field) == getattr(task_request, field)
        events = [
            e for e in engine.handle.drain_events() if getattr(e, "kind", None) == "compaction"
        ]
        assert len(events) == 1
        assert events[0].outcome == "compacted"
        assert events[0].model_calls == 1
        assert events[0].failure_reason is None
    finally:
        await engine.shutdown_session()
