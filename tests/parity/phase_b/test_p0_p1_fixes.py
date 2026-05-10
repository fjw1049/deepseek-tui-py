"""Parity tests for the P0/P1 batch fixes (2026-05-10).

Covers:
- P0#1 ``max_tool_round_trips`` default raised to 100
- P0#2 ``edit_file`` Rust-parity ``search``/``replace`` schema + legacy alias
- P0#3 ``Usage`` field aliases for DeepSeek wire keys + nested reasoning_tokens
- P0#4 ``reasoning_effort`` / ``temperature`` / ``top_p`` / ``extra_body``
        flow through ``TurnLoop`` into the streamed request
- P0#5 ``DeepSeekClient`` httpx ``read=None`` so per-chunk ``asyncio.wait_for``
        owns SSE idle timing
- P1#7 ``CancelRequestOp`` sets ``cancel_event`` defensively
- P1#9 ``grep_files`` regex support
- P1#10 ``exec_shell`` ``timeout_ms`` argument validation + foreground kill
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.ops import CancelRequestOp
from deepseek_tui.engine.turn_loop import TurnLoop
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamEvent, Usage
from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.file_tools import EditFileTool
from deepseek_tui.tools.search_tools import GrepFilesTool
from deepseek_tui.tools.shell_tools import (
    EXEC_DEFAULT_TIMEOUT_MS,
    EXEC_MAX_TIMEOUT_MS,
    ExecShellTool,
    _resolve_timeout_ms,
)

# --- P0#1 ----------------------------------------------------------------


def test_engine_default_max_tool_round_trips_is_100() -> None:
    """Mirror of Rust ``EngineConfig::default`` (engine.rs:155 = 100)."""
    sig = inspect.signature(Engine.__init__)
    assert sig.parameters["max_tool_round_trips"].default == 100
    sig_create = inspect.signature(Engine.create)
    assert sig_create.parameters["max_tool_round_trips"].default == 100


# --- P0#2 ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_file_accepts_rust_parity_keys(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello world", encoding="utf-8")
    tool = EditFileTool()
    result = await tool.execute(
        {"path": str(target), "search": "world", "replace": "python"},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success
    assert target.read_text(encoding="utf-8") == "hello python"


@pytest.mark.asyncio
async def test_edit_file_accepts_legacy_alias_keys(tmp_path: Path) -> None:
    """Legacy ``old_string``/``new_string`` still works for backward compat."""
    target = tmp_path / "f.txt"
    target.write_text("alpha beta", encoding="utf-8")
    tool = EditFileTool()
    result = await tool.execute(
        {"path": str(target), "old_string": "beta", "new_string": "gamma"},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success
    assert target.read_text(encoding="utf-8") == "alpha gamma"


@pytest.mark.asyncio
async def test_edit_file_requires_unique_match(tmp_path: Path) -> None:
    """Python keeps the unique-match safety guard (vs Rust replace-all).

    Documented as a partial parity in HANDOVER.
    """
    target = tmp_path / "f.txt"
    target.write_text("foo foo", encoding="utf-8")
    tool = EditFileTool()
    with pytest.raises(ToolError, match="not unique"):
        await tool.execute(
            {"path": str(target), "search": "foo", "replace": "bar"},
            ToolContext(working_directory=tmp_path),
        )


def test_edit_file_schema_advertises_rust_keys() -> None:
    schema = EditFileTool().input_schema()
    props = schema["properties"]
    assert "search" in props and "replace" in props
    assert schema["required"] == ["path", "search", "replace"]


# --- P0#3 ----------------------------------------------------------------


def test_usage_validates_deepseek_prompt_tokens() -> None:
    """DeepSeek returns ``prompt_tokens``/``completion_tokens`` — must populate."""
    usage = Usage.model_validate(
        {"prompt_tokens": 12, "completion_tokens": 7}
    )
    assert usage.input_tokens == 12
    assert usage.output_tokens == 7


def test_usage_extracts_cache_hit_miss() -> None:
    usage = Usage.model_validate(
        {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "prompt_cache_hit_tokens": 60,
            "prompt_cache_miss_tokens": 40,
        }
    )
    assert usage.cache_read_input_tokens == 60
    assert usage.cache_creation_input_tokens == 40


def test_usage_extracts_nested_reasoning_tokens() -> None:
    """Mirror of Rust ``parse_usage`` (client.rs) which reads
    ``completion_tokens_details.reasoning_tokens``."""
    usage = Usage.model_validate(
        {
            "prompt_tokens": 5,
            "completion_tokens": 200,
            "completion_tokens_details": {"reasoning_tokens": 150},
        }
    )
    assert usage.reasoning_tokens == 150


def test_usage_explicit_reasoning_tokens_wins_over_nested() -> None:
    usage = Usage.model_validate(
        {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "reasoning_tokens": 9,
            "completion_tokens_details": {"reasoning_tokens": 1},
        }
    )
    assert usage.reasoning_tokens == 9


# --- P0#4 ----------------------------------------------------------------


class _CapturingClient(LLMClient):
    """Records the MessageRequest passed to stream_chat_completion."""

    def __init__(self) -> None:
        super().__init__()
        self.captured: MessageRequest | None = None

    async def stream_chat_completion(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        self.captured = request
        if False:  # pragma: no cover — preserve generator typing
            yield StreamDone()
        yield StreamDone()


@pytest.mark.asyncio
async def test_turn_loop_forwards_reasoning_effort_and_sampling() -> None:
    """The rebuilt ``stream_request`` keeps reasoning_effort/temperature/top_p."""
    client = _CapturingClient()
    loop = TurnLoop(client=client)
    request = MessageRequest(
        model="deepseek-reasoner",
        messages=[Message.user("hi")],
        reasoning_effort="medium",
        temperature=0.4,
        top_p=0.9,
        extra_body={"foo": "bar"},
    )

    async def emit(_event: object) -> None:
        return None

    await loop.run(request, emit, asyncio.Event(), tools=[])
    captured = client.captured
    assert captured is not None
    assert captured.reasoning_effort == "medium"
    assert captured.temperature == 0.4
    assert captured.top_p == 0.9
    assert captured.extra_body == {"foo": "bar"}


# --- P0#5 ----------------------------------------------------------------


def test_deepseek_client_uses_unbounded_read_timeout() -> None:
    """httpx ``read=None`` so per-chunk asyncio.wait_for owns idle detection."""
    client = DeepSeekClient(api_key="secret", timeout_seconds=42.0)
    http = client._get_http_client()
    timeout = http.timeout
    assert timeout.read is None
    assert timeout.connect == 42.0
    assert timeout.write == 42.0


# --- P1#7 ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_request_op_sets_cancel_event() -> None:
    """Even without ``handle.cancel()``, queueing CancelRequestOp must cancel."""
    handle = EngineHandle()

    class _NopClient(LLMClient):
        async def stream_chat_completion(
            self, request: MessageRequest
        ) -> AsyncIterator[StreamEvent]:
            yield StreamDone()

    engine = Engine(handle=handle, client=_NopClient())
    runner = asyncio.create_task(engine.run())
    await handle.send_op(CancelRequestOp(reason="explicit"))
    # Yield enough to let engine.run consume the op.
    for _ in range(20):
        if handle.cancel_event.is_set():
            break
        await asyncio.sleep(0)
    assert handle.cancel_event.is_set()
    runner.cancel()
    try:
        await runner
    except asyncio.CancelledError:
        pass


# --- P1#9 ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_files_supports_regex(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("foo123\nfoobar\nbaz", encoding="utf-8")
    tool = GrepFilesTool()
    result = await tool.execute(
        {"pattern": r"foo\d+", "path": str(tmp_path)},
        ToolContext(working_directory=tmp_path),
    )
    assert result.success
    assert "foo123" in result.content
    assert "foobar" not in result.content


@pytest.mark.asyncio
async def test_grep_files_ignore_case(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Hello World\n", encoding="utf-8")
    tool = GrepFilesTool()
    result = await tool.execute(
        {"pattern": "hello", "path": str(tmp_path), "ignore_case": True},
        ToolContext(working_directory=tmp_path),
    )
    assert "Hello World" in result.content


@pytest.mark.asyncio
async def test_grep_files_invalid_regex_raises(tmp_path: Path) -> None:
    tool = GrepFilesTool()
    with pytest.raises(ToolError, match="invalid regex"):
        await tool.execute(
            {"pattern": "[unclosed", "path": str(tmp_path)},
            ToolContext(working_directory=tmp_path),
        )


# --- P1#10 ---------------------------------------------------------------


def test_resolve_timeout_ms_default() -> None:
    assert _resolve_timeout_ms(None) == EXEC_DEFAULT_TIMEOUT_MS


def test_resolve_timeout_ms_validates_max() -> None:
    with pytest.raises(ToolError, match="<="):
        _resolve_timeout_ms(EXEC_MAX_TIMEOUT_MS + 1)


def test_resolve_timeout_ms_rejects_negative() -> None:
    with pytest.raises(ToolError, match=">= 1"):
        _resolve_timeout_ms(0)


def test_resolve_timeout_ms_rejects_non_int() -> None:
    with pytest.raises(ToolError, match="integer"):
        _resolve_timeout_ms("120000")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_exec_shell_kills_on_timeout(tmp_path: Path) -> None:
    """Long-running command is terminated when timeout_ms expires."""
    tool = ExecShellTool()
    ctx = ToolContext(working_directory=tmp_path)
    result = await tool.execute(
        {"command": "sleep 5", "timeout_ms": 50},
        ctx,
    )
    assert not result.success
    assert result.metadata["timed_out"] is True
    assert result.metadata["timeout_ms"] == 50


def test_exec_shell_schema_advertises_timeout_ms() -> None:
    schema = ExecShellTool().input_schema()
    props = schema["properties"]
    assert "timeout_ms" in props
    assert props["timeout_ms"]["maximum"] == EXEC_MAX_TIMEOUT_MS


# --- P1#11 (HTTP pre-stream retry) ---------------------------------------


@pytest.mark.asyncio
async def test_pre_stream_retry_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """503 responses are retried before any SSE chunks are yielded."""
    from contextlib import asynccontextmanager

    from deepseek_tui.client import deepseek as ds_module

    attempts = {"count": 0}

    class _FakeResponse:
        def __init__(self, status: int) -> None:
            self.status_code = status
            self.request = httpx.Request("POST", "http://test")

        async def aread(self) -> bytes:
            return b"server overloaded"

    class _FakeEventSource:
        def __init__(self, status: int, events: list[Any]) -> None:
            self.response = _FakeResponse(status)
            self._events = events

        async def __aenter__(self) -> _FakeEventSource:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def aiter_sse(self) -> AsyncIterator[Any]:
            for ev in self._events:
                yield ev

    class _FakeSSE:
        def __init__(self, data: str) -> None:
            self.data = data

    @asynccontextmanager
    async def fake_aconnect_sse(*_a: Any, **_kw: Any) -> AsyncIterator[Any]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield _FakeEventSource(503, [])
        else:
            yield _FakeEventSource(
                200,
                [
                    _FakeSSE(
                        '{"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}],'
                        '"usage":{"prompt_tokens":1,"completion_tokens":1}}'
                    ),
                    _FakeSSE("[DONE]"),
                ],
            )

    monkeypatch.setattr(ds_module, "aconnect_sse", fake_aconnect_sse)
    real_sleep = asyncio.sleep

    async def _instant_sleep(_t: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(ds_module.asyncio, "sleep", _instant_sleep)

    client = DeepSeekClient(api_key="k")
    request = MessageRequest(model="deepseek-chat")
    events = [ev async for ev in client.stream_chat_completion(request)]
    assert attempts["count"] == 2
    assert any(getattr(e, "text", "") == "hi" for e in events)
