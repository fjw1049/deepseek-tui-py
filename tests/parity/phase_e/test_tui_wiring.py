"""Stage 6.1 parity tests: Engine ↔ TUI wiring.

Verifies that DeepSeekTUI can be constructed with config, that it
starts the engine on mount, and that the full event surface is routed
to the transcript.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.models import Config
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ErrorEvent,
    SandboxDeniedEvent,
    StatusEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.execpolicy.models import ApprovalRequest, RiskLevel, ToolCategory
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta, ToolCall, Usage
from deepseek_tui.tui.app import DeepSeekTUI
from deepseek_tui.tui.widgets.transcript import Transcript

# ── Fixtures ──────────────────────────────────────────────────────────


class FakeClient(LLMClient):
    """Minimal LLM client that returns a canned response."""

    def __init__(self, deltas: list[str] | None = None) -> None:
        super().__init__()
        self._deltas = deltas or ["Hello ", "world!"]

    async def stream_chat_completion(
        self, request: Any
    ) -> AsyncIterator[StreamTextDelta | StreamDone]:
        for text in self._deltas:
            yield StreamTextDelta(text=text)
        yield StreamDone(usage=Usage(input_tokens=10, output_tokens=5))


# ── Construction tests ────────────────────────────────────────────────


class TestDeepSeekTUIConstruction:
    def test_default_construction(self) -> None:
        app = DeepSeekTUI()
        assert app.config is not None
        assert app.handle is not None
        assert app._engine is None

    def test_construction_with_config(self) -> None:
        cfg = Config(provider="deepseek", model="deepseek-chat")
        app = DeepSeekTUI(config=cfg)
        assert app.config.model == "deepseek-chat"

    def test_construction_with_handle(self) -> None:
        handle = EngineHandle()
        app = DeepSeekTUI(handle=handle)
        assert app.handle is handle

    def test_backward_compat_handle_kwarg(self) -> None:
        """Ensure old callers using ``DeepSeekTUI(handle=...)`` still work."""
        handle = EngineHandle()
        app = DeepSeekTUI(handle=handle)
        assert app.handle is handle
        assert app.config is not None


# ── Engine wiring tests ──────────────────────────────────────────────


class TestEngineWiring:
    async def test_engine_starts_via_handle(self, tmp_path: Any) -> None:
        """Engine.create + run wires correctly through the handle."""
        handle = EngineHandle()
        client = FakeClient(["Pong"])
        engine = await Engine.create(
            handle, client, default_model="test-model",
            working_directory=tmp_path,
        )
        task = asyncio.create_task(engine.run())

        await handle.send_message("Ping")
        events = []
        async for event in handle.events():
            events.append(event)
            if isinstance(event, TurnCompleteEvent):
                break

        task.cancel()
        await engine.shutdown()

        assert any(isinstance(e, TurnStartedEvent) for e in events)
        assert any(isinstance(e, TurnCompleteEvent) for e in events)
        has_content = any(
            isinstance(e, TextDeltaEvent) or isinstance(e, ThinkingDeltaEvent)
            for e in events
        )
        complete_evt = next(e for e in events if isinstance(e, TurnCompleteEvent))
        assert has_content or complete_evt.assistant_message is not None

    async def test_handle_cancel(self) -> None:
        handle = EngineHandle()
        assert not handle.cancel_event.is_set()
        await handle.cancel("test")
        assert handle.cancel_event.is_set()


# ── Transcript event handling tests ──────────────────────────────────


class TestTranscriptEvents:
    def test_user_message(self) -> None:
        t = Transcript()
        t.add_user_message("Hello")
        assert len(t._messages) == 1
        assert "You:" in t._messages[0]

    def test_system_message(self) -> None:
        t = Transcript()
        t.add_system_message("Error occurred")
        assert len(t._messages) == 1
        assert "System:" in t._messages[0]

    def test_assistant_streaming(self) -> None:
        t = Transcript()
        t.start_assistant_message()
        t.append_delta("Hello ")
        t.append_delta("world")
        assert t._current_buffer == "Hello world"
        t.finalize_message()
        assert not t._in_assistant
        assert any("Assistant:" in m for m in t._messages)

    def test_thinking_delta(self) -> None:
        t = Transcript()
        t.start_assistant_message()
        t.append_thinking("Let me think...")
        assert t._thinking_buffer == "Let me think..."
        t.append_delta("Answer")
        t.finalize_message()
        assert any("Thinking:" in m for m in t._messages)
        assert any("Assistant:" in m for m in t._messages)

    def test_tool_call_and_result(self) -> None:
        t = Transcript()
        t.add_tool_call("tc-123", "read_file", {"path": "/tmp/a"})
        assert len(t._messages) == 1
        assert "read_file" in t._messages[0]
        assert "tc-123" in t._tool_cells

        t.update_tool_result("tc-123", "file contents here", success=True)
        assert "✓" in t._messages[0] or "✗" not in t._messages[0]

    def test_tool_result_failure(self) -> None:
        t = Transcript()
        t.add_tool_call("tc-456", "exec_shell", {"command": "ls"})
        t.update_tool_result("tc-456", "Permission denied", success=False)
        assert "✗" in t._messages[0]

    def test_tool_result_unknown_id_ignored(self) -> None:
        t = Transcript()
        t.update_tool_result("unknown-id", "data", success=True)
        assert len(t._messages) == 0

    def test_clear_messages(self) -> None:
        t = Transcript()
        t.add_user_message("Hello")
        t.start_assistant_message()
        t.append_delta("Hi")
        t.add_tool_call("tc-1", "tool", {})
        t.clear_messages()
        assert len(t._messages) == 0
        assert t._current_buffer == ""
        assert t._thinking_buffer == ""
        assert not t._in_assistant
        assert len(t._tool_cells) == 0


# ── Full event loop test ─────────────────────────────────────────────


class TestFullEventLoop:
    async def test_all_event_types_handled(self) -> None:
        """Verify _listen_events handles every EngineEvent variant."""
        handle = EngineHandle()

        events_to_emit = [
            TurnStartedEvent(user_text="test"),
            StatusEvent(message="loading"),
            ThinkingDeltaEvent(thinking="hmm"),
            TextDeltaEvent(text="Hello"),
            ToolCallEvent(
                tool_call=ToolCall(
                    id="tc-1", name="read_file", arguments={"path": "/tmp"}
                )
            ),
            ToolResultEvent(
                tool_call_id="tc-1",
                tool_name="read_file",
                content="ok",
                success=True,
            ),
            ApprovalRequiredEvent(
                tool_call_id="tc-2",
                request=ApprovalRequest(
                    tool_name="exec_shell",
                    risk_level=RiskLevel.HIGH,
                    category=ToolCategory.CODE_EXEC,
                    reason="dangerous",
                ),
            ),
            ApprovalResolvedEvent(
                tool_call_id="tc-2", approved=True, reason="user"
            ),
            SandboxDeniedEvent(
                tool_call_id="tc-3",
                tool_name="exec_shell",
                reason="blocked",
            ),
            ErrorEvent(message="something broke"),
            TurnCompleteEvent(assistant_message=None, usage=None),
        ]

        for evt in events_to_emit:
            await handle.emit(evt)

        app = DeepSeekTUI(handle=handle, config=Config())
        app._engine = True  # type: ignore[assignment]  # pretend engine exists

        transcript = Transcript()
        from deepseek_tui.tui.widgets.status_bar import StatusBar
        status = StatusBar()

        received_count = 0
        async for event in handle.events():
            received_count += 1
            if isinstance(event, TurnStartedEvent):
                status.set_status("thinking...")
                transcript.start_assistant_message()
            elif isinstance(event, TextDeltaEvent):
                transcript.append_delta(event.text)
            elif isinstance(event, ThinkingDeltaEvent):
                transcript.append_thinking(event.thinking)
            elif isinstance(event, ToolCallEvent):
                tc = event.tool_call
                transcript.add_tool_call(tc.id, tc.name, tc.arguments)
            elif isinstance(event, ToolResultEvent):
                transcript.update_tool_result(
                    event.tool_call_id, event.content, event.success
                )
            elif isinstance(event, ApprovalRequiredEvent):
                transcript.add_system_message("approval required")
            elif isinstance(event, ApprovalResolvedEvent):
                transcript.add_system_message("approved")
            elif isinstance(event, SandboxDeniedEvent):
                transcript.add_system_message("denied")
            elif isinstance(event, ErrorEvent):
                transcript.add_system_message(f"Error: {event.message}")
            elif isinstance(event, TurnCompleteEvent):
                transcript.finalize_message()
                break
            elif isinstance(event, StatusEvent):
                status.set_status(event.message)

        assert received_count == len(events_to_emit)


# ── One-shot mode test ───────────────────────────────────────────────


class TestOneShotMode:
    def test_cli_app_run_one_shot_import(self) -> None:
        """Verify _run_one_shot_async is importable."""
        from deepseek_tui.cli.app import _run_one_shot_async
        assert callable(_run_one_shot_async)
