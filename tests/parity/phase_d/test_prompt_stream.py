"""Parity tests for /prompt/stream → Engine → LLM event flow (Stage 4.1.next.next).

Two layers:

- **Fake client**: exercises the AppRuntime.stream_prompt → Engine →
  turn_loop → engine_event_to_sse bridge in isolation. Hermetic,
  runs always.
- **Real DeepSeek API**: optional, runs when an API key is reachable
  via DEEPSEEK_API_KEY env or project config.toml. Proves the end-to-end
  pipe against a live model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.app_server.engine_bridge import engine_event_to_sse
from deepseek_tui.app_server.runtime import AppRuntime
from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.models import Config, HooksConfig
from deepseek_tui.engine.events import (
    ErrorEvent,
    StatusEvent,
    TextDeltaEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
)
from deepseek_tui.protocol.messages import Message, Role, TextBlock
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta, Usage
from tests._real_api import (
    get_deepseek_api_key,
    get_deepseek_base_url,
    has_deepseek_api_key,
)


class _FakeStreamingClient(LLMClient):
    """Emits a fixed script: thinking → text delta → done."""

    def __init__(self, deltas: list[str] | None = None) -> None:
        super().__init__()
        self._deltas = deltas or ["Hello ", "world"]

    def stream_chat_completion(
        self, _request: MessageRequest
    ) -> AsyncIterator[object]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[object]:
        for chunk in self._deltas:
            yield StreamTextDelta(text=chunk)
        yield StreamDone(usage=Usage(input_tokens=5, output_tokens=2))


class TestEngineBridgeSerialization:
    """Unit-test the EngineEvent → SSE dict bridge without any Engine."""

    def test_turn_started(self) -> None:
        out = engine_event_to_sse(TurnStartedEvent(user_text="hi"))
        assert out == {"event": "turn_started", "user_text": "hi"}

    def test_text_delta(self) -> None:
        out = engine_event_to_sse(TextDeltaEvent(text="hello"))
        assert out == {"event": "text_delta", "text": "hello"}

    def test_status(self) -> None:
        out = engine_event_to_sse(StatusEvent(message="thinking"))
        assert out == {"event": "status", "message": "thinking"}

    def test_error(self) -> None:
        out = engine_event_to_sse(ErrorEvent(message="boom", retryable=True))
        assert out == {
            "event": "error",
            "message": "boom",
            "retryable": True,
        }

    def test_turn_complete_with_text_blocks(self) -> None:
        msg = Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="done")],
        )
        out = engine_event_to_sse(
            TurnCompleteEvent(
                assistant_message=msg,
                usage=Usage(input_tokens=3, output_tokens=1),
            )
        )
        assert out["event"] == "turn_complete"
        assert out["assistant_text"] == "done"
        assert out["usage"] is not None
        assert out["usage"]["input_tokens"] == 3
        assert out["usage"]["output_tokens"] == 1

    def test_turn_complete_none_message(self) -> None:
        out = engine_event_to_sse(
            TurnCompleteEvent(assistant_message=None, usage=None)
        )
        assert out["assistant_text"] == ""
        assert out["usage"] is None


class TestStreamPromptWithFakeClient:
    """AppRuntime.stream_prompt drives Engine when an LLMClient is present."""

    async def test_emits_real_engine_event_stream(self, tmp_path: Path) -> None:
        cfg = Config()
        # Disable all hook sinks so stdout stays clean during the test.
        cfg.hooks = HooksConfig()
        rt = await AppRuntime.create(
            config=cfg,
            working_directory=tmp_path,
            llm_client=_FakeStreamingClient(deltas=["Hi ", "there"]),
        )
        try:
            events: list[dict[str, Any]] = []
            async for frame in rt.stream_prompt({"input": "hello"}):
                events.append(frame)
                if frame.get("event") == "turn_complete":
                    break
        finally:
            await rt.shutdown()

        event_names = [e["event"] for e in events]
        # Must have seen turn_started, at least one text_delta, and turn_complete
        assert "turn_started" in event_names
        assert "text_delta" in event_names
        assert "turn_complete" in event_names
        # Fixed delta payload round-trips
        deltas = [e["text"] for e in events if e["event"] == "text_delta"]
        assert "".join(deltas).strip() == "Hi there"

    async def test_placeholder_when_no_client(self, tmp_path: Path) -> None:
        cfg = Config()
        cfg.hooks = HooksConfig()
        rt = await AppRuntime.create(config=cfg, working_directory=tmp_path)
        try:
            events: list[dict[str, Any]] = []
            async for frame in rt.stream_prompt({"input": "hello"}):
                events.append(frame)
        finally:
            await rt.shutdown()
        # Rust-parity 3-frame placeholder when no LLM injected
        assert [e["event"] for e in events] == [
            "response_start",
            "response_delta",
            "response_end",
        ]


# --------------------------------------------------------------------------
# Live DeepSeek API end-to-end — runs when key is reachable
# --------------------------------------------------------------------------

REAL_API_REASON = (
    "Needs DEEPSEEK_API_KEY env var or api_key in project config.toml"
)


@pytest.mark.skipif(not has_deepseek_api_key(), reason=REAL_API_REASON)
class TestStreamPromptRealApi:
    async def test_live_stream_produces_text_deltas(self, tmp_path: Path) -> None:
        from deepseek_tui.client.deepseek import DeepSeekClient
        from deepseek_tui.tools.registry import ToolRegistry

        api_key = get_deepseek_api_key()
        assert api_key is not None
        client = DeepSeekClient(
            api_key=api_key,
            base_url=get_deepseek_base_url(),
            timeout_seconds=60.0,
        )

        cfg = Config()
        cfg.hooks = HooksConfig()
        # Skip heavier features so live test stays focused on streaming.
        cfg.features.mcp = False
        cfg.features.subagents = False
        cfg.features.tasks = False
        rt = await AppRuntime.create(
            config=cfg,
            working_directory=tmp_path,
            llm_client=client,
        )
        # This test isolates the engine→SSE bridge, not tool-schema
        # compatibility with the remote model. Swap in an empty registry
        # so the live API call carries no tools payload. Tool-over-LLM
        # wiring is covered by its own integration suite.
        if rt._tool_runtime is not None:
            rt._tool_runtime.registry = ToolRegistry()
        try:
            events: list[dict[str, Any]] = []
            async for frame in rt.stream_prompt(
                {
                    "input": (
                        "Reply with just the single word 'pong'. "
                        "No punctuation, no extra text."
                    ),
                    "model": "deepseek-v4-flash",
                }
            ):
                events.append(frame)
                # Non-retryable errors are terminal; retryable ones are
                # mid-stream heartbeats from turn_loop and we keep going.
                ev_kind = frame.get("event")
                if ev_kind == "turn_complete":
                    break
                if ev_kind == "error" and not frame.get("retryable", False):
                    break
        finally:
            await rt.shutdown()

        event_names = [e["event"] for e in events]
        # Required structural events
        assert "turn_started" in event_names, event_names
        # Only fatal errors count against the test; retryable stream
        # interruptions are tolerated (turn_loop handles them itself).
        fatal_errors = [
            e for e in events
            if e["event"] == "error" and not e.get("retryable", False)
        ]
        assert not fatal_errors, f"live stream fatal error: {fatal_errors}"
        assert any(
            n in event_names for n in ("text_delta", "turn_complete")
        ), event_names
        # Either we streamed text deltas or the completion carries text.
        text = "".join(e["text"] for e in events if e["event"] == "text_delta")
        if not text:
            completes = [e for e in events if e["event"] == "turn_complete"]
            if completes:
                text = completes[-1].get("assistant_text", "")
        assert "pong" in text.lower(), f"model did not echo 'pong': {text!r}"
        # Either we streamed text deltas or the completion carries text.
        text = "".join(e["text"] for e in events if e["event"] == "text_delta")
        if not text:
            completes = [e for e in events if e["event"] == "turn_complete"]
            if completes:
                text = completes[-1].get("assistant_text", "")
        assert "pong" in text.lower(), f"model did not echo 'pong': {text!r}"
