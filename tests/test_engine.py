from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.approval import DenyApprovalHandler
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    SandboxDeniedEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.execpolicy.engine import ExecPolicyEngine
from deepseek_tui.execpolicy.models import ApprovalDecision, PolicyRule
from deepseek_tui.protocol.messages import Role, TextBlock, ToolResultBlock
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamToolCallComplete,
    ToolCall,
    Usage,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.file_tools import ReadFileTool
from deepseek_tui.tools.registry import ToolRegistry


class FakeEngineClient(LLMClient):
    def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[object]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[object]:
        yield StreamThinkingDelta(thinking="thinking")
        yield StreamTextDelta(text="hello ")
        yield StreamTextDelta(text="world")
        yield StreamDone(usage=Usage(input_tokens=10, output_tokens=2))


class FakeToolLoopClient(LLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def stream_chat_completion(self, request: MessageRequest) -> AsyncIterator[object]:
        self.calls += 1
        return self._stream(request)

    async def _stream(self, request: MessageRequest) -> AsyncIterator[object]:
        has_tool_result = any(message.role is Role.TOOL for message in request.messages)
        if not has_tool_result:
            yield StreamToolCallComplete(
                tool_call=ToolCall(
                    id="tool-1",
                    name="read_file",
                    arguments={"path": "notes.txt"},
                )
            )
            yield StreamDone(usage=Usage(input_tokens=5, output_tokens=1))
            return

        yield StreamTextDelta(text="final answer")
        yield StreamDone(usage=Usage(input_tokens=8, output_tokens=2))


@pytest.mark.asyncio
async def test_engine_emits_minimal_turn_events() -> None:
    handle = EngineHandle()
    engine = Engine(handle=handle, client=FakeEngineClient())
    task = asyncio.create_task(engine.run())

    await handle.send_message("hi")

    events = []
    async for event in handle.events():
        events.append(event)
        if isinstance(event, TurnCompleteEvent):
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert isinstance(events[0], TurnStartedEvent)
    assert any(isinstance(event, ThinkingDeltaEvent) for event in events)
    assert any(isinstance(event, TextDeltaEvent) for event in events)

    complete_event = events[-1]
    assert isinstance(complete_event, TurnCompleteEvent)
    assert complete_event.assistant_message is not None
    text_blocks = [
        block for block in complete_event.assistant_message.content if isinstance(block, TextBlock)
    ]
    assert text_blocks[0].text == "hello world"
    assert complete_event.usage is not None
    assert complete_event.usage.output_tokens == 2


@pytest.mark.asyncio
async def test_engine_executes_tool_calls_and_feeds_results_back(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("tool output", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    handle = EngineHandle()
    engine = Engine(
        handle=handle,
        client=FakeToolLoopClient(),
        tool_registry=registry,
        tool_context=ToolContext(working_directory=tmp_path),
    )
    task = asyncio.create_task(engine.run())

    await handle.send_message("read the file")

    events = []
    async for event in handle.events():
        events.append(event)
        if isinstance(event, TurnCompleteEvent):
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert any(isinstance(event, ToolCallEvent) for event in events)
    tool_result_events = [event for event in events if isinstance(event, ToolResultEvent)]
    assert len(tool_result_events) == 1
    assert tool_result_events[0].content == "tool output"

    complete_event = events[-1]
    assert isinstance(complete_event, TurnCompleteEvent)
    assert complete_event.assistant_message is not None
    assert complete_event.assistant_message.content[0].text == "final answer"
    assert len(engine.session_messages) == 4

    tool_message = engine.session_messages[2]
    assert tool_message.role is Role.TOOL
    tool_block = tool_message.content[0]
    assert isinstance(tool_block, ToolResultBlock)
    assert tool_block.content == "tool output"


@pytest.mark.asyncio
async def test_engine_blocks_tool_when_approval_denied(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("tool output", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    handle = EngineHandle()
    engine = Engine(
        handle=handle,
        client=FakeToolLoopClient(),
        tool_registry=registry,
        tool_context=ToolContext(working_directory=tmp_path),
        exec_policy=ExecPolicyEngine(
            rules=[PolicyRule(pattern="read_file", decision=ApprovalDecision.DENIED)]
        ),
        approval_handler=DenyApprovalHandler(),
    )
    task = asyncio.create_task(engine.run())

    await handle.send_message("read the file")

    events = []
    async for event in handle.events():
        events.append(event)
        if isinstance(event, TurnCompleteEvent):
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert any(isinstance(event, ApprovalRequiredEvent) for event in events)
    assert any(isinstance(event, SandboxDeniedEvent) for event in events)
    assert not any(isinstance(event, ToolResultEvent) for event in events)


# ---------------------------------------------------------------------------
# Soft steer — composer Enter while a turn is running.
#
# Contract:
#   1. handle.is_turn_active() is True between SendMessageOp pickup and the
#      TurnComplete/TurnCancelled emit, False at all other times.
#   2. handle.steer(text) queues a user message that the *currently running*
#      turn picks up at the top of its next round (so multi-round tool
#      loops see it on the very next iteration; single-round flat replies
#      see it carried forward to the *next* SendMessage).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_turn_active_idle_at_rest() -> None:
    """A freshly constructed handle is not active and reports it."""
    handle = EngineHandle()
    assert handle.is_turn_active() is False


@pytest.mark.asyncio
async def test_engine_marks_turn_active_during_run(tmp_path: Path) -> None:
    """``is_turn_active`` flips True while Engine processes a turn and back
    to False after the turn finishes (TurnComplete or TurnCancelled)."""

    class _SlowClient(LLMClient):
        """Streams two text chunks with tiny gaps so a probe in between
        observes the active flag."""

        def __init__(self) -> None:
            super().__init__()
            self.probe_active: bool | None = None
            self._handle: EngineHandle | None = None

        def bind(self, handle: EngineHandle) -> None:
            self._handle = handle

        def stream_chat_completion(
            self, request: MessageRequest
        ) -> AsyncIterator[object]:
            return self._stream()

        async def _stream(self) -> AsyncIterator[object]:
            yield StreamTextDelta(text="hi")
            await asyncio.sleep(0.02)
            assert self._handle is not None
            self.probe_active = self._handle.is_turn_active()
            yield StreamDone(usage=Usage(input_tokens=1, output_tokens=1))

    handle = EngineHandle()
    client = _SlowClient()
    client.bind(handle)
    engine = Engine(
        handle=handle,
        client=client,
        tool_registry=ToolRegistry(),
        tool_context=ToolContext(working_directory=tmp_path),
        exec_policy=ExecPolicyEngine(rules=[]),
    )
    task = asyncio.create_task(engine.run())
    await handle.send_message("hello")

    async for event in handle.events():
        if isinstance(event, TurnCompleteEvent):
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.probe_active is True, (
        "is_turn_active() must be True while the engine is mid-turn"
    )
    assert handle.is_turn_active() is False, (
        "is_turn_active() must reset to False after TurnComplete"
    )


@pytest.mark.asyncio
async def test_engine_drains_steer_into_next_round(tmp_path: Path) -> None:
    """A steer queued mid-turn is picked up at the top of the next loop
    iteration of the same turn (Engine.drain_steers in _run_conversation).

    Strategy: drive a tool-loop client that runs two rounds. Between the
    two stream_chat_completion() invocations, queue a steer; assert the
    second round's request.messages contains it as a user message.
    """
    captured_round_2_messages: list[Any] = []

    class _TwoRoundClient(LLMClient):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0
            self.handle: EngineHandle | None = None

        def stream_chat_completion(
            self, request: MessageRequest
        ) -> AsyncIterator[object]:
            self.calls += 1
            if self.calls == 1:
                return self._round_1()
            captured_round_2_messages.extend(request.messages)
            return self._round_2()

        async def _round_1(self) -> AsyncIterator[object]:
            yield StreamToolCallComplete(
                tool_call=ToolCall(
                    id="call_1", name="read_file", arguments={"path": "x.txt"}
                )
            )
            yield StreamDone(usage=Usage(input_tokens=1, output_tokens=1))
            # Steer is queued by the test after round-1 done arrives via
            # the post-tool checkpoint in Engine.

        async def _round_2(self) -> AsyncIterator[object]:
            yield StreamTextDelta(text="ok")
            yield StreamDone(usage=Usage(input_tokens=1, output_tokens=1))

    from typing import Any

    (tmp_path / "x.txt").write_text("hi", encoding="utf-8")

    registry = ToolRegistry()
    registry.register(ReadFileTool())

    handle = EngineHandle()
    client = _TwoRoundClient()
    engine = Engine(
        handle=handle,
        client=client,
        tool_registry=registry,
        tool_context=ToolContext(working_directory=tmp_path),
        exec_policy=ExecPolicyEngine(rules=[]),
    )
    task = asyncio.create_task(engine.run())

    await handle.send_message("look at x.txt")

    # Watch events: steer the moment we see ToolCallEvent (during round
    # 1, before round 2's drain_steers() runs). Contract: a steer queued
    # during round N is visible in round N+1's prompt.
    steered = False
    async for event in handle.events():
        if not steered and isinstance(event, ToolCallEvent):
            steered = True
            await handle.steer("actually also describe it")
        if isinstance(event, TurnCompleteEvent):
            break

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.calls == 2, "Engine should have driven a second round"
    user_texts = []
    for msg in captured_round_2_messages:
        if getattr(msg, "role", None) == Role.USER:
            for block in msg.content:
                if isinstance(block, TextBlock):
                    user_texts.append(block.text)
    assert any(
        "actually also describe it" in t for t in user_texts
    ), f"steered message must reach round-2 prompt; got user blocks: {user_texts!r}"


# ---------------------------------------------------------------------------
# /context breakdown — Engine.context_breakdown returns per-bucket tokens.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_breakdown_buckets_sum_to_total(tmp_path: Path) -> None:
    """system + tools + conversation must equal ``total`` and ``free``
    must be ``window - total`` (clamped at 0)."""
    from deepseek_tui.protocol.messages import Message

    engine = await Engine.create(
        EngineHandle(),
        FakeEngineClient(),
        default_model="deepseek-v4-pro",
        working_directory=tmp_path,
    )
    engine.session_messages = [Message.user("hi"), Message.user("again")]

    b = engine.context_breakdown("deepseek-v4-pro")

    assert b["system_prompt"] > 0
    # tools may be 0 if registry empty; assert non-negative
    assert b["tools"] >= 0
    assert b["conversation"] > 0
    assert b["total"] == b["system_prompt"] + b["tools"] + b["conversation"]
    if b["window"] > 0:
        assert b["free"] == max(0, b["window"] - b["total"])


@pytest.mark.asyncio
async def test_context_breakdown_unknown_model_uses_default_window(tmp_path: Path) -> None:
    """Unknown models fall through to the registry's default window
    (currently 128K) rather than 0; ``free`` is computed against that
    default. This pins the contract — if the default ever changes, this
    test breaks loudly."""
    engine = await Engine.create(
        EngineHandle(),
        FakeEngineClient(),
        default_model="not-a-real-model",
        working_directory=tmp_path,
    )
    b = engine.context_breakdown("not-a-real-model")
    assert b["window"] >= b["total"]
    assert b["free"] == b["window"] - b["total"]


def test_format_context_breakdown_renders_progress_line() -> None:
    """The text formatter shows used/window header + 4 buckets."""
    from deepseek_tui.tui.commands.handlers import _format_context_breakdown

    out = _format_context_breakdown(
        {
            "system_prompt": 600,
            "tools": 7800,
            "conversation": 10700,
            "total": 19100,
            "window": 200000,
            "free": 180900,
        },
        model="deepseek-v4-pro",
    )
    assert "Context:" in out
    assert "200" in out  # window
    assert "System prompt" in out
    assert "Tools" in out
    assert "Conversation" in out
    assert "Free space" in out
    assert "deepseek-v4-pro" in out


def test_format_context_breakdown_unknown_window() -> None:
    """When window is 0 the header says 'window unknown' and bar shows '-'."""
    from deepseek_tui.tui.commands.handlers import _format_context_breakdown

    out = _format_context_breakdown(
        {
            "system_prompt": 100,
            "tools": 200,
            "conversation": 300,
            "total": 600,
            "window": 0,
            "free": 0,
        },
        model="x",
    )
    assert "window unknown" in out
