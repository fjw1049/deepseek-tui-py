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
