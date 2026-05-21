"""Tests for hooks ↔ Engine bridge integration."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.engine.events import (
    ApprovalResolvedEvent,
    SessionEndedEvent,
    SessionStartedEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.hooks.dispatcher import HookDispatcher
from deepseek_tui.hooks.events import (
    ApprovalLifecycleEvent,
    ResponseDeltaEvent,
    SessionLifecycleEvent,
    ToolLifecycleEvent,
    event_to_dict,
)
from deepseek_tui.hooks.sinks import (
    HookSink,
    JsonlHookSink,
    ShellHookSink,
)
from deepseek_tui.protocol.responses import ToolCall


# --- Collector sink for testing ---


class CollectorSink(HookSink):
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


# --- EngineHandle bridge tests ---


class TestEngineHandleBridge:
    async def test_tool_call_event_bridges_to_tool_lifecycle_start(self):
        collector = CollectorSink()
        dispatcher = HookDispatcher()
        dispatcher.add_sink(collector)
        handle = EngineHandle(hooks=dispatcher)

        tc = ToolCall(id="tc-1", name="read_file", arguments={"path": "/tmp/x"})
        await handle.emit(ToolCallEvent(tool_call=tc))

        assert len(collector.events) == 1
        evt = collector.events[0]
        assert isinstance(evt, ToolLifecycleEvent)
        assert evt.phase == "start"
        assert evt.tool_name == "read_file"
        assert evt.payload == {"arguments": {"path": "/tmp/x"}}

    async def test_tool_result_success_bridges_to_complete(self):
        collector = CollectorSink()
        dispatcher = HookDispatcher()
        dispatcher.add_sink(collector)
        handle = EngineHandle(hooks=dispatcher)

        await handle.emit(
            ToolResultEvent(
                tool_call_id="tc-1",
                tool_name="read_file",
                content="hello",
                success=True,
            )
        )

        evt = collector.events[0]
        assert isinstance(evt, ToolLifecycleEvent)
        assert evt.phase == "complete"

    async def test_tool_result_error_bridges_to_error_phase(self):
        collector = CollectorSink()
        dispatcher = HookDispatcher()
        dispatcher.add_sink(collector)
        handle = EngineHandle(hooks=dispatcher)

        await handle.emit(
            ToolResultEvent(
                tool_call_id="tc-2",
                tool_name="exec_shell",
                content="fail",
                success=False,
            )
        )

        evt = collector.events[0]
        assert isinstance(evt, ToolLifecycleEvent)
        assert evt.phase == "error"

    async def test_session_started_bridges(self):
        collector = CollectorSink()
        dispatcher = HookDispatcher()
        dispatcher.add_sink(collector)
        handle = EngineHandle(hooks=dispatcher)

        await handle.emit(SessionStartedEvent(session_id="sess-abc"))

        evt = collector.events[0]
        assert isinstance(evt, SessionLifecycleEvent)
        assert evt.phase == "start"
        assert evt.session_id == "sess-abc"

    async def test_session_ended_bridges(self):
        collector = CollectorSink()
        dispatcher = HookDispatcher()
        dispatcher.add_sink(collector)
        handle = EngineHandle(hooks=dispatcher)

        await handle.emit(SessionEndedEvent(session_id="sess-abc", turns=5))

        evt = collector.events[0]
        assert isinstance(evt, SessionLifecycleEvent)
        assert evt.phase == "end"
        assert evt.turns == 5

    async def test_approval_resolved_bridges(self):
        collector = CollectorSink()
        dispatcher = HookDispatcher()
        dispatcher.add_sink(collector)
        handle = EngineHandle(hooks=dispatcher)

        await handle.emit(
            ApprovalResolvedEvent(
                tool_call_id="tc-3", approved=True, reason="approved_session"
            )
        )

        evt = collector.events[0]
        assert isinstance(evt, ApprovalLifecycleEvent)
        assert evt.phase == "resolved"
        assert evt.reason == "approved_session"

    async def test_no_hooks_no_error(self):
        handle = EngineHandle(hooks=None)
        await handle.emit(SessionStartedEvent(session_id="x"))
        # Should not raise — just queues to event_queue

    async def test_text_delta_bridges_to_response_delta(self):
        collector = CollectorSink()
        dispatcher = HookDispatcher()
        dispatcher.add_sink(collector)
        handle = EngineHandle(hooks=dispatcher)
        handle.set_response_id("resp-99")

        await handle.emit(TextDeltaEvent(text="hello"))

        assert len(collector.events) == 1
        from deepseek_tui.hooks.events import ResponseDeltaEvent

        evt = collector.events[0]
        assert isinstance(evt, ResponseDeltaEvent)
        assert evt.response_id == "resp-99"
        assert evt.delta == "hello"

    async def test_approval_required_bridges(self):
        from deepseek_tui.engine.events import ApprovalRequiredEvent
        from deepseek_tui.execpolicy.models import ApprovalRequest, RiskLevel, ToolCategory

        collector = CollectorSink()
        dispatcher = HookDispatcher()
        dispatcher.add_sink(collector)
        handle = EngineHandle(hooks=dispatcher)

        req = ApprovalRequest(
            tool_name="exec_shell",
            risk_level=RiskLevel.HIGH,
            category=ToolCategory.CODE_EXEC,
            reason="shell command",
        )
        await handle.emit(
            ApprovalRequiredEvent(tool_call_id="tc-4", request=req)
        )

        evt = collector.events[0]
        assert isinstance(evt, ApprovalLifecycleEvent)
        assert evt.phase == "requested"
        assert evt.reason == "shell command"

    async def test_sink_exception_does_not_propagate(self):
        class BrokenSink(HookSink):
            async def emit(self, event):
                raise RuntimeError("boom")

        dispatcher = HookDispatcher()
        dispatcher.add_sink(BrokenSink())
        handle = EngineHandle(hooks=dispatcher)

        # Should not raise
        await handle.emit(SessionStartedEvent(session_id="x"))


# --- JsonlHookSink async test ---


class TestJsonlHookSinkAsync:
    async def test_writes_to_file(self, tmp_path):
        log_path = tmp_path / "hooks.jsonl"
        sink = JsonlHookSink(log_path)

        await sink.emit(SessionLifecycleEvent(session_id="s1", phase="start"))

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event"]["type"] == "session_lifecycle"
        assert data["event"]["session_id"] == "s1"
        assert "at" in data


# --- ShellHookSink tests ---


class TestShellHookSink:
    async def test_matching_event_runs_command(self, tmp_path):
        marker = tmp_path / "fired.txt"
        sink = ShellHookSink(
            event_filter="session_lifecycle",
            command=f"cat > {marker}",
            timeout=5.0,
        )

        await sink.emit(SessionLifecycleEvent(session_id="s1", phase="start"))

        content = marker.read_text()
        data = json.loads(content)
        assert data["type"] == "session_lifecycle"
        assert data["session_id"] == "s1"

    async def test_non_matching_event_skipped(self, tmp_path):
        marker = tmp_path / "should_not_exist.txt"
        sink = ShellHookSink(
            event_filter="tool_lifecycle",
            command=f"touch {marker}",
            timeout=5.0,
        )

        await sink.emit(SessionLifecycleEvent(session_id="s1", phase="start"))

        assert not marker.exists()

    async def test_timeout_kills_process(self):
        sink = ShellHookSink(
            event_filter="session_lifecycle",
            command="sleep 60",
            timeout=0.1,
        )
        # Should not hang — timeout kills the process
        await sink.emit(SessionLifecycleEvent(session_id="s1", phase="start"))


# --- event_to_dict coverage for SessionLifecycleEvent ---


class TestEventToDict:
    def test_session_lifecycle_start(self):
        d = event_to_dict(SessionLifecycleEvent(session_id="abc", phase="start"))
        assert d == {"type": "session_lifecycle", "session_id": "abc", "phase": "start"}

    def test_session_lifecycle_end_with_turns(self):
        d = event_to_dict(
            SessionLifecycleEvent(session_id="abc", phase="end", turns=10)
        )
        assert d == {
            "type": "session_lifecycle",
            "session_id": "abc",
            "phase": "end",
            "turns": 10,
        }
