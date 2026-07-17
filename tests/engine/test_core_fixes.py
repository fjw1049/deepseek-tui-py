"""Regression tests for core engine fixes (cancel chain, retry, budget, compaction)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.engine.capacity import (
    KEEP_RECENT_MESSAGES,
    plan_compaction,
    validate_compaction_summary,
)
from deepseek_tui.engine.prompts import (
    COMPACT_CONSUMER_HINT,
    COMPACT_TEMPLATE,
    build_system_prompt,
)
from deepseek_tui.engine.context import context_input_budget
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.turn import (
    TURN_MAX_OUTPUT_TOKENS,
    TurnLoop,
    TurnOutcomeStatus,
)
from deepseek_tui.protocol.messages import Message, Role, ToolUseBlock
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamEvent,
    StreamTextDelta,
)


# --- context_input_budget -------------------------------------------------


def test_context_input_budget_small_window_still_checked():
    """128K-window models must get a positive budget, not None.

    Previously the fixed 262K output reservation drove the budget negative
    and the overflow precheck was skipped entirely for these models.
    """
    budget = context_input_budget("gpt-4o", TURN_MAX_OUTPUT_TOKENS)
    assert budget is not None
    assert budget > 0


def test_context_input_budget_large_window_unchanged_shape():
    budget = context_input_budget("deepseek-v4-pro", TURN_MAX_OUTPUT_TOKENS)
    assert budget is not None
    assert budget > 500_000


# --- plan_compaction orphan tool_result -----------------------------------


def _tool_round_tail() -> list[Message]:
    """History whose keep-window boundary lands on tool results."""
    msgs: list[Message] = []
    for i in range(8):
        msgs.append(Message.user(f"question {i}"))
        msgs.append(Message.assistant(f"answer {i}"))
    # assistant w/ tool_calls followed by 3 tool results, then final text.
    msgs.append(
        Message.assistant_with_tools(
            [ToolUseBlock(id=f"tc{i}", name="read_file", input={}) for i in range(3)]
        )
    )
    for i in range(3):
        msgs.append(Message.tool_result(f"tc{i}", f"result {i}"))
    return msgs


def test_plan_compaction_does_not_orphan_tool_results():
    messages = _tool_round_tail()
    plan = plan_compaction(messages)
    kept = sorted(plan.pinned_indices)
    first_kept = kept[0]
    # The first pinned message must not be a tool result whose parent
    # assistant(tool_calls) message got summarized away.
    assert messages[first_kept].role != Role.TOOL
    # The parent assistant message carrying the tool_use blocks is pinned.
    parent_idx = len(messages) - 4  # assistant_with_tools
    assert parent_idx in plan.pinned_indices


def test_plan_compaction_plain_history_keeps_recent_window():
    messages = [Message.user(f"m{i}") for i in range(10)]
    plan = plan_compaction(messages)
    expected = set(range(10 - KEEP_RECENT_MESSAGES, 10))
    assert expected <= plan.pinned_indices


# --- structured compaction handoff ----------------------------------------


def test_validate_compaction_summary_accepts_structured_handoff():
    text = (
        "### Goal\nShip compaction handoff.\n\n"
        "### Constraints\nNone\n\n"
        "### Progress\n#### Done\nWired summarizer.\n"
        "#### In Progress\nNone\n#### Blocked\nNone\n\n"
        "### Key Decisions\nUse compact.md as summarizer contract.\n\n"
        "### Next step\nRun unit tests.\n"
    )
    assert validate_compaction_summary(text) is None


def test_validate_compaction_summary_rejects_empty_and_prose():
    assert validate_compaction_summary("") == "compaction summary came back empty"
    assert validate_compaction_summary("   ") == "compaction summary came back empty"
    assert "too short" in (validate_compaction_summary("short prose") or "")
    prose = (
        "The user asked to fix compaction. We discussed prompts and pinning. "
        "Next we should implement validation."
    )
    err = validate_compaction_summary(prose)
    assert err is not None
    assert "missing required headings" in err


def test_build_system_prompt_uses_consumer_hint_not_empty_template():
    prompt = build_system_prompt(project_context_enabled=False)
    assert COMPACT_CONSUMER_HINT in prompt
    assert "After Compaction" in prompt
    # Empty Goal skeleton must not pollute the main agent system prompt.
    assert "### Goal\n[The user's high-level objective" not in prompt
    # Summarizer contract still loads the structured template.
    assert "### Goal" in COMPACT_TEMPLATE()
    assert "### Next step" in COMPACT_TEMPLATE()


# --- EngineHandle.reset_cancel --------------------------------------------


def test_reset_cancel_preserves_event_identity():
    handle = EngineHandle()
    original = handle.cancel_event
    original.set()
    handle.reset_cancel()
    assert handle.cancel_event is original
    assert not handle.cancel_event.is_set()


# --- TurnLoop stream error handling ----------------------------------------


class _ScriptedClient(LLMClient):
    """Yields a fixed script of stream events per attempt."""

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        super().__init__(RetryConfig(base_delay=0.0, max_delay=0.0))
        self.scripts = scripts
        self.calls = 0
        self.requests: list[MessageRequest] = []

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        script = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        for event in script:
            yield event


async def _run_turn(client: LLMClient):
    loop = TurnLoop(client)
    events = []

    async def emit(event):
        events.append(event)

    result = await loop.run(
        request=MessageRequest(
            model="deepseek-chat",
            messages=[Message.user("hi")],
        ),
        emit=emit,
        cancel_event=asyncio.Event(),
        tools=None,
    )
    return result, events


@pytest.mark.asyncio
async def test_mid_content_stream_error_fails_turn_without_duplication():
    """StreamError after content must FAIL the turn, not let a replayed
    stream append duplicate deltas and then report SUCCESS."""
    client = _ScriptedClient(
        [
            [
                StreamTextDelta(text="hello "),
                StreamError(message="connection reset", retryable=True),
                # Simulates the client-level full-stream replay that used
                # to get appended onto the existing buffer.
                StreamTextDelta(text="hello again"),
                StreamDone(usage=None),
            ]
        ]
    )
    result, _ = await _run_turn(client)
    assert result.outcome == TurnOutcomeStatus.FAILED
    assert result.error_message == "connection reset"
    text = "".join(
        b.text for b in (result.assistant_message.content if result.assistant_message else [])
        if hasattr(b, "text")
    )
    assert "hello again" not in text


@pytest.mark.asyncio
async def test_pre_content_stream_errors_terminate():
    """A provider that fails before any content must not retry forever."""
    client = _ScriptedClient(
        [[StreamError(message="boom", retryable=True)]]
    )
    result, _ = await asyncio.wait_for(_run_turn(client), timeout=10)
    assert result.outcome == TurnOutcomeStatus.FAILED
    # 1 initial + 2 transparent retries
    assert client.calls == 3


@pytest.mark.asyncio
async def test_successful_stream_unaffected():
    client = _ScriptedClient(
        [[StreamTextDelta(text="ok"), StreamDone(usage=None)]]
    )
    result, _ = await _run_turn(client)
    assert result.outcome == TurnOutcomeStatus.SUCCESS
    assert client.calls == 1


@pytest.mark.asyncio
async def test_glm_gets_reasoning_output_headroom():
    """GLM-5.2 streams large reasoning_content; the legacy 4096 default was
    exhausted by reasoning alone, truncating the round before any answer
    content was produced. It must request enough output headroom to finish
    thinking *and* emit the answer."""
    client = _ScriptedClient([[StreamDone(usage=None)]])
    loop = TurnLoop(client)

    await loop.run(
        request=MessageRequest(
            model="glm-5.2",
            messages=[Message.user("hi")],
        ),
        emit=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        tools=None,
    )

    assert client.requests[0].max_tokens == 32_768
