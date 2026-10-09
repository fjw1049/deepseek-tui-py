"""Human takeover keeps the turn alive and fences obsolete model/tool work."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.events import ModelRequestInterruptedEvent, ToolCallEvent, ToolResultEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.pause import RunPause
from deepseek_tui.engine.turn import TurnResult
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolError, ToolResult


async def make_engine(tmp_path):
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle, client=AsyncMock(), working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False,
        )), start_mcp=False,
    )
    return engine, handle


async def test_takeover_closes_model_and_resumes_same_conversation(tmp_path):
    engine, handle = await make_engine(tmp_path)
    started, closed = asyncio.Event(), asyncio.Event()
    requests = []

    async def model(request, emit, *args, **kwargs):
        requests.append([m.text_content() for m in request.messages])
        if len(requests) == 1:
            await emit(ToolCallEvent(ToolCall(
                id="never-run", name="read_file", arguments={"path": "old"},
            )))
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        return TurnResult(assistant_message=Message.assistant("done"))

    engine.turn_loop.run = model
    # Even at the last model round, human intervention must not exhaust the loop.
    engine.max_tool_round_trips = 0
    messages = [Message.user("Read the US trends")]
    task = asyncio.create_task(engine._run_conversation(messages, "deepseek-chat", "sys", None))
    try:
        await asyncio.wait_for(started.wait(), 2)
        handle.pause.pause()
        await asyncio.wait_for(closed.wait(), 1)
        await handle.steer("Keep the US region")
        await asyncio.sleep(0.01)
        assert not task.done()
        assert len(requests) == 1
        handle.resume_context = "Manual actions unknown. Fresh observation: region=US."
        handle.pause.resume()
        result = await asyncio.wait_for(task, 2)
        assert result.assistant_message.text_content() == "done"
        assert len(requests) == 2
        assert requests[1].count("Read the US trends") == 1
        assert sum("Fresh observation" in text for text in requests[1]) == 1
        assert any("Keep the US region" in text for text in requests[1])
        assert handle._op_queue.empty()  # no synthetic SendMessageOp
        events = list(handle.drain_events())
        assert any(isinstance(event, ModelRequestInterruptedEvent) for event in events)
        assert any(isinstance(event, ToolResultEvent) and event.tool_call_id == "never-run"
                   and event.metadata.get("not_executed") for event in events)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.shutdown_session()


async def test_takeover_keeps_completed_result_but_discards_remaining_tools(tmp_path):
    engine, handle = await make_engine(tmp_path)
    started, finished = asyncio.Event(), asyncio.Event()
    calls, requests = [], []

    async def execute(name, args, context):
        calls.append(args["path"])
        started.set()
        await finished.wait()
        return ToolResult(True, "ALREADY EXECUTED")

    # Record actual effects; pausing must preserve their completed results.
    engine.tool_registry.execute = execute
    async def model(request, *args, **kwargs):
        requests.append([m.model_dump_json() for m in request.messages])
        if len(requests) == 1:
            return TurnResult(assistant_message=None, tool_calls=[
                ToolCall(id="first", name="read_file", arguments={"path": "one"}),
                ToolCall(id="second", name="read_file", arguments={"path": "two"}),
            ])
        return TurnResult(assistant_message=Message.assistant("done"))

    # Make the two read calls sequential to exercise the pending dispatch boundary.
    engine.tool_registry.get("read_file").supports_parallel = lambda: False
    engine.turn_loop.run = model
    task = asyncio.create_task(engine._run_conversation(
        [Message.user("Read two files")], "deepseek-chat", "sys", None,
    ))
    try:
        await asyncio.wait_for(started.wait(), 2)
        handle.pause.pause()
        finished.set()
        await asyncio.sleep(0.02)
        assert calls == ["one"]
        assert not task.done()
        handle.resume_context = "Human intervention ended. Recheck current files."
        handle.pause.resume()
        await asyncio.wait_for(task, 2)
        assert calls == ["one"]
        assert sum("ALREADY EXECUTED" in text for text in requests[1]) == 1
        assert any("Not executed: human intervention" in text for text in requests[1])
    finally:
        finished.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.shutdown_session()


async def test_approval_does_not_release_obsolete_tool_after_takeover(tmp_path, monkeypatch):
    engine, handle = await make_engine(tmp_path)
    started, approved = asyncio.Event(), asyncio.Event()
    engine._tool_batch_generation = handle.pause.generation
    async def approval(*args, **kwargs):
        started.set()
        await approved.wait()
        return False
    engine._handle_approval_flow = approval
    engine.tool_registry.execute = AsyncMock()
    from deepseek_tui.tools.approval import build_approval_request

    monkeypatch.setattr(
        "deepseek_tui.tools.approval.approval_request_for_tool",
        lambda *args: build_approval_request("shell", []),
    )
    call = ToolCall(id="shell", name="exec_shell", arguments={"command": "echo hi"})
    task = asyncio.create_task(engine._execute_single_tool_impl(call, [], "deepseek-chat"))
    try:
        await asyncio.wait_for(started.wait(), 1)
        handle.pause.pause()
        handle.pause.resume()
        approved.set()
        with pytest.raises(ToolError, match="Not executed"):
            await task
        engine.tool_registry.execute.assert_not_awaited()
    finally:
        approved.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.shutdown_session()


async def test_paused_wait_is_cancelable_and_does_not_consume_response_timeout():
    pause, cancel, response = RunPause(), asyncio.Event(), asyncio.Event()
    pause.pause()
    watcher = asyncio.create_task(pause.wait_active_timeout(response, 0.02, cancel))
    await asyncio.sleep(0.04)
    assert not watcher.done()
    pause.resume()
    response.set()
    await asyncio.wait_for(watcher, 1)
    pause.pause()
    waiting = asyncio.create_task(pause.wait(cancel))
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiting, 1)
