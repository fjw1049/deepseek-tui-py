"""Parity tests for hooks dispatcher + AppRuntime integration (Stage 4.2).

Mirror of Rust ``crates/hooks/src/lib.rs`` (170 lines) and the
``AppRuntime → HookDispatcher`` wiring. Covers:

- Each sink type (stdout / jsonl / webhook) emits Rust-parity payload
- Webhook retry budget = 2, 200ms × retries backoff
- HookDispatcher fan-out to multiple sinks
- AppRuntime emits ResponseStart/Delta/End on /prompt and stream_prompt
- AppRuntime emits ToolLifecycle precheck/complete/error for /tool
- AppRuntime emits JobLifecycle snapshot on /jobs
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from deepseek_tui.app_server import AppRuntime
from deepseek_tui.config.models import Config, HooksConfig
from deepseek_tui.hooks.dispatcher import HookDispatcher
from deepseek_tui.hooks.events import (
    HookEvent,
    JobLifecycleEvent,
    ResponseStartEvent,
    ToolLifecycleEvent,
)
from deepseek_tui.hooks.sinks import HookSink, JsonlHookSink, WebhookHookSink


class _CapturingSink(HookSink):
    """Test-only sink that records every event received."""

    def __init__(self) -> None:
        self.events: list[HookEvent] = []

    async def emit(self, event: HookEvent) -> None:
        self.events.append(event)


class TestDispatcher:
    async def test_fan_out_to_all_sinks(self) -> None:
        s1, s2 = _CapturingSink(), _CapturingSink()
        d = HookDispatcher()
        d.add_sink(s1)
        d.add_sink(s2)
        await d.emit(ResponseStartEvent(response_id="r-1"))
        assert len(s1.events) == 1
        assert len(s2.events) == 1

    async def test_sink_failure_does_not_block(self) -> None:
        class Angry(HookSink):
            async def emit(self, event: HookEvent) -> None:
                raise RuntimeError("boom")

        good = _CapturingSink()
        d = HookDispatcher()
        d.add_sink(Angry())
        d.add_sink(good)
        await d.emit(ResponseStartEvent(response_id="r-2"))
        assert len(good.events) == 1


class TestJsonlSink:
    async def test_appends_jsonl(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        sink = JsonlHookSink(path)
        await sink.emit(ResponseStartEvent(response_id="r-a"))
        await sink.emit(ResponseStartEvent(response_id="r-b"))
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        assert parsed[0]["event"]["type"] == "response_start"
        assert parsed[0]["event"]["response_id"] == "r-a"
        assert "at" in parsed[0]

    async def test_tool_lifecycle_preserves_payload(self, tmp_path: Path) -> None:
        path = tmp_path / "tl.jsonl"
        sink = JsonlHookSink(path)
        ev = ToolLifecycleEvent(
            response_id="rid",
            tool_name="exec_shell",
            phase="precheck",
            payload={"command": "ls"},
        )
        await sink.emit(ev)
        record = json.loads(path.read_text().strip())
        assert record["event"]["type"] == "tool_lifecycle"
        assert record["event"]["payload"] == {"command": "ls"}


class TestWebhookRetry:
    async def test_retries_twice_then_fails(self, monkeypatch) -> None:
        calls = {"n": 0}

        class _Resp:
            def __init__(self, status: int) -> None:
                self.status_code = status
                self.is_success = 200 <= status < 300

        class _Client:
            async def post(self, _url: str, *, json: Any) -> _Resp:  # noqa: A002
                calls["n"] += 1
                return _Resp(500)

            async def aclose(self) -> None:
                pass

        sink = WebhookHookSink("http://example/")
        sink._client = _Client()  # type: ignore[assignment]

        sleep_calls: list[float] = []

        async def fast_sleep(d: float) -> None:
            sleep_calls.append(d)

        monkeypatch.setattr(
            "deepseek_tui.hooks.sinks.asyncio.sleep", fast_sleep
        )

        with pytest.raises(RuntimeError, match="non-success"):
            await sink.emit(ResponseStartEvent(response_id="r"))
        assert calls["n"] == 3  # initial + 2 retries (Rust parity)
        assert sleep_calls == [0.2, 0.4]

    async def test_success_short_circuits(self, monkeypatch) -> None:
        class _Resp:
            status_code = 200
            is_success = True

        class _Client:
            async def post(self, _url: str, *, json: Any) -> _Resp:  # noqa: A002
                return _Resp()

            async def aclose(self) -> None:
                pass

        sink = WebhookHookSink("http://example/")
        sink._client = _Client()  # type: ignore[assignment]
        await sink.emit(ResponseStartEvent(response_id="r"))


@pytest_asyncio.fixture
async def runtime_with_capture(
    tmp_path: Path,
) -> AsyncIterator[tuple[AppRuntime, _CapturingSink]]:
    sink = _CapturingSink()
    dispatcher = HookDispatcher()
    dispatcher.add_sink(sink)
    cfg = Config()
    # Explicitly disable built-in hook sinks so only the capture fires.
    cfg.hooks = HooksConfig()
    from deepseek_tui.tools.runtime import create_tool_runtime

    tool_runtime = await create_tool_runtime(
        config=cfg, working_directory=tmp_path
    )
    rt = AppRuntime(
        config=cfg,
        tool_runtime=tool_runtime,
        working_directory=tmp_path,
        hooks=dispatcher,
    )
    try:
        yield rt, sink
    finally:
        await rt.shutdown()


class TestAppRuntimeHookEmission:
    async def test_prompt_emits_response_lifecycle(
        self, runtime_with_capture: tuple[AppRuntime, _CapturingSink]
    ) -> None:
        rt, sink = runtime_with_capture
        await rt.handle_prompt({"input": "hi"})
        kinds = [type(ev).__name__ for ev in sink.events]
        assert kinds == [
            "ResponseStartEvent",
            "ResponseDeltaEvent",
            "ResponseEndEvent",
        ]

    async def test_stream_prompt_emits_response_lifecycle(
        self, runtime_with_capture: tuple[AppRuntime, _CapturingSink]
    ) -> None:
        rt, sink = runtime_with_capture
        frames: list[dict[str, Any]] = []
        async for fr in rt.stream_prompt({"input": "x"}):
            frames.append(fr)
        assert len(sink.events) == 3
        assert len(frames) == 3

    async def test_tool_emits_precheck_and_complete(
        self, runtime_with_capture: tuple[AppRuntime, _CapturingSink]
    ) -> None:
        rt, sink = runtime_with_capture
        await rt.handle_tool(
            {"call": {"name": "diagnostics", "arguments": {}}}
        )
        tool_events = [
            ev for ev in sink.events if isinstance(ev, ToolLifecycleEvent)
        ]
        phases = [ev.phase for ev in tool_events]
        assert phases == ["precheck", "complete"]
        assert all(ev.tool_name == "diagnostics" for ev in tool_events)

    async def test_tool_error_emits_error_phase(
        self, runtime_with_capture: tuple[AppRuntime, _CapturingSink]
    ) -> None:
        rt, sink = runtime_with_capture
        await rt.handle_tool(
            {"call": {"name": "does_not_exist", "arguments": {}}}
        )
        tool_events = [
            ev for ev in sink.events if isinstance(ev, ToolLifecycleEvent)
        ]
        assert [ev.phase for ev in tool_events] == ["precheck", "error"]

    async def test_jobs_emits_snapshot(
        self, runtime_with_capture: tuple[AppRuntime, _CapturingSink]
    ) -> None:
        rt, sink = runtime_with_capture
        await rt.jobs()
        job_events = [
            ev for ev in sink.events if isinstance(ev, JobLifecycleEvent)
        ]
        assert len(job_events) == 1
        assert job_events[0].phase == "snapshot"
        assert "tasks=" in (job_events[0].detail or "")


class TestConfigBuildsDispatcher:
    async def test_stdout_flag_adds_stdout_sink(self, tmp_path: Path) -> None:
        cfg = Config()
        cfg.hooks = HooksConfig(stdout=True)
        rt = AppRuntime(config=cfg, working_directory=tmp_path)
        try:
            from deepseek_tui.hooks.sinks import StdoutHookSink as _StdoutHookSink

            assert any(isinstance(s, _StdoutHookSink) for s in rt.hooks.sinks)
        finally:
            await rt.shutdown()

    async def test_jsonl_path_adds_jsonl_sink(self, tmp_path: Path) -> None:
        cfg = Config()
        cfg.hooks = HooksConfig(jsonl_path=tmp_path / "h.jsonl")
        rt = AppRuntime(config=cfg, working_directory=tmp_path)
        try:
            jsonl_sinks = [
                s for s in rt.hooks.sinks if isinstance(s, JsonlHookSink)
            ]
            assert len(jsonl_sinks) == 1
            assert jsonl_sinks[0].path == tmp_path / "h.jsonl"
        finally:
            await rt.shutdown()

    async def test_webhook_urls_skip_blank(self, tmp_path: Path) -> None:
        cfg = Config()
        cfg.hooks = HooksConfig(webhook_urls=["http://a/", "  ", "http://b/"])
        rt = AppRuntime(config=cfg, working_directory=tmp_path)
        try:
            webhooks = [
                s for s in rt.hooks.sinks if isinstance(s, WebhookHookSink)
            ]
            assert {w.url for w in webhooks} == {"http://a/", "http://b/"}
        finally:
            await rt.shutdown()
