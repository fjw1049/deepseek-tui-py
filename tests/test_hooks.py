"""Tests for hooks system."""

import json
from pathlib import Path

import pytest

from deepseek_tui.hooks import (
    HookDispatcher,
    JsonlHookSink,
    ResponseDeltaEvent,
    ResponseStartEvent,
    StdoutHookSink,
    ToolLifecycleEvent,
)


@pytest.mark.asyncio
async def test_stdout_sink(capsys):
    """Test stdout sink emits JSON."""
    sink = StdoutHookSink()
    event = ResponseStartEvent(response_id="resp-1")
    await sink.emit(event)
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["type"] == "response_start"
    assert data["response_id"] == "resp-1"


@pytest.mark.asyncio
async def test_jsonl_sink(tmp_path: Path):
    """Test JSONL sink appends events."""
    log_path = tmp_path / "hooks.jsonl"
    sink = JsonlHookSink(log_path)
    event1 = ResponseStartEvent(response_id="resp-1")
    event2 = ResponseDeltaEvent(response_id="resp-1", delta="hello")
    await sink.emit(event1)
    await sink.emit(event2)
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 2
    data1 = json.loads(lines[0])
    assert data1["event"]["type"] == "response_start"
    data2 = json.loads(lines[1])
    assert data2["event"]["type"] == "response_delta"
    assert data2["event"]["delta"] == "hello"


@pytest.mark.asyncio
async def test_dispatcher_broadcasts():
    """Test dispatcher broadcasts to multiple sinks."""
    events_captured = []

    class CaptureSink:
        async def emit(self, event):
            events_captured.append(event)

    dispatcher = HookDispatcher()
    dispatcher.add_sink(CaptureSink())
    dispatcher.add_sink(CaptureSink())
    event = ToolLifecycleEvent(
        response_id="resp-1", tool_name="read_file", phase="start", payload={}
    )
    await dispatcher.emit(event)
    assert len(events_captured) == 2
    assert all(e.tool_name == "read_file" for e in events_captured)


@pytest.mark.asyncio
async def test_dispatcher_best_effort():
    """Test dispatcher continues on sink failure."""
    events_captured = []

    class FailingSink:
        async def emit(self, event):
            raise RuntimeError("sink error")

    class CaptureSink:
        async def emit(self, event):
            events_captured.append(event)

    dispatcher = HookDispatcher()
    dispatcher.add_sink(FailingSink())
    dispatcher.add_sink(CaptureSink())
    event = ResponseStartEvent(response_id="resp-1")
    await dispatcher.emit(event)
    assert len(events_captured) == 1
