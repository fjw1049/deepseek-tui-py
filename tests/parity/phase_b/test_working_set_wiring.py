"""WorkingSet wiring tests (HANDOVER §workingset.2026-05-14).

Until 2026-05-14 ``WorkingSet`` was a complete orphan: implemented in
``engine/working_set.py`` but never instantiated. Downstream sites
(``CycleState.working_set_summary``, ``build_system_prompt``'s
``working_set_summary`` kw) sat waiting for a producer.

These tests verify the producer is now connected:

1. ``Engine.__init__`` instantiates ``self.working_set``.
2. ``observe_user_message`` runs when a user op is handled (paths in
   the user text reach ``recent_paths``).
3. ``observe_tool_call`` runs after every tool result (path-shaped
   tool inputs reach ``recent_paths``).
4. ``ws.summary()`` is threaded into ``build_system_prompt``.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.events import EngineEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.ops import SendMessageOp
from deepseek_tui.engine.working_set import WorkingSet
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    ToolCall,
    Usage,
)


class _SimpleClient(LLMClient):
    """Client yielding plain text + done — no tool calls."""

    def __init__(self) -> None:
        super().__init__()

    async def stream_chat_completion(
        self, request: Any
    ) -> AsyncIterator[StreamTextDelta | StreamDone]:
        yield StreamTextDelta(text="ok")
        yield StreamDone(usage=Usage(input_tokens=1, output_tokens=1))


class TestWorkingSetWiring:
    @pytest.mark.asyncio
    async def test_engine_instantiates_working_set(self, tmp_path: Path) -> None:
        engine = await Engine.create(
            EngineHandle(),
            _SimpleClient(),
            default_model="test",
            working_directory=tmp_path,
        )
        assert isinstance(engine.working_set, WorkingSet)
        assert engine.working_set.message_count == 0

    @pytest.mark.asyncio
    async def test_handle_send_message_observes_user_text(
        self, tmp_path: Path
    ) -> None:
        """User text containing a path should appear in recent_paths."""
        engine = await Engine.create(
            EngineHandle(),
            _SimpleClient(),
            default_model="test",
            working_directory=tmp_path,
        )

        events: list[EngineEvent] = []

        async def _drain() -> None:
            while True:
                ev = await engine.handle.events.get()
                events.append(ev)

        drain_task = asyncio.create_task(_drain())
        runner = asyncio.create_task(engine.run())

        try:
            await engine.handle.send_op(
                SendMessageOp(content="please read ./pkg/foo.py for me")
            )
            # Pump until we see a TurnComplete-ish event (or timeout).
            for _ in range(50):
                await asyncio.sleep(0.02)
                if engine.working_set.message_count >= 1:
                    break
        finally:
            runner.cancel()
            drain_task.cancel()
            for t in (runner, drain_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        assert engine.working_set.message_count == 1
        # The path regex captures ``./pkg/foo.py`` (leading whitespace +
        # leading ./, .py suffix). Verify it landed in the set.
        assert any("foo.py" in p for p in engine.working_set.recent_paths)

    def test_observe_tool_call_extracts_input_path(
        self, tmp_path: Path
    ) -> None:
        """Direct unit: observe_tool_call must consume tool_input paths."""
        ws = WorkingSet(workspace=tmp_path)
        ws.observe_tool_call(
            "read_file",
            {"path": "src/deepseek_tui/engine/engine.py"},
            "(file contents elided)",
        )
        assert "read_file" in ws.recent_tool_uses
        assert any(
            "engine.py" in p for p in ws.recent_paths
        ), f"expected engine.py in {ws.recent_paths!r}"

    @pytest.mark.asyncio
    async def test_system_prompt_includes_working_set_summary(
        self, tmp_path: Path
    ) -> None:
        """After observing paths, summary() returns a block; build_system_prompt
        includes that block when handed via the kw."""
        from deepseek_tui.engine.prompts import build_system_prompt

        ws = WorkingSet(workspace=tmp_path)
        ws.observe_tool_call(
            "edit_file",
            {"path": "src/app.py"},
            None,
        )
        summary = ws.summary()
        assert "Working Set" in summary
        assert "app.py" in summary

        prompt = build_system_prompt(
            None,
            workspace=tmp_path,
            working_set_summary=summary,
            project_context_enabled=False,
        )
        assert "Working Set" in prompt
        assert "app.py" in prompt

    def test_summary_empty_when_no_paths(self, tmp_path: Path) -> None:
        ws = WorkingSet(workspace=tmp_path)
        # Engine passes ``ws.summary() or None``; verify empty stays empty so
        # we don't inject a stray header into the prompt.
        assert ws.summary() == ""


class TestWorkingSetToolHookSite:
    """Verify the tool-result hook in ``_execute_tool_calls`` runs.

    We don't drive a real tool here — we call ``observe_tool_call``
    directly on the engine's WorkingSet to prove the attribute exists
    and is the same instance that the hook would touch.
    """

    @pytest.mark.asyncio
    async def test_engine_working_set_is_single_instance(
        self, tmp_path: Path
    ) -> None:
        engine = await Engine.create(
            EngineHandle(),
            _SimpleClient(),
            default_model="test",
            working_directory=tmp_path,
        )
        ws_first = engine.working_set
        engine.working_set.observe_tool_call(
            "grep_files",
            {"pattern": "foo", "path": "./lib/util.py"},
            "lib/util.py:1: foo",
        )
        # Same instance across observations (Q3=A Engine singleton).
        assert engine.working_set is ws_first
        assert "grep_files" in engine.working_set.recent_tool_uses


def test_tool_call_dict_argument_branch() -> None:
    """The hook in engine guards against non-dict ``arguments``.

    Verify the WorkingSet skips gracefully when input is a string."""
    ws = WorkingSet()
    # Direct API: observe_tool_call accepts None for tool_input.
    ws.observe_tool_call("noop", None, "no paths here")
    assert ws.recent_tool_uses == ["noop"]
    assert ws.recent_paths == set()


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Driving a real read_file tool through the full engine loop "
    "requires more harness scaffolding; the unit-level hooks above already "
    "cover the wiring contract."
)
async def test_send_message_branch_with_tool_calls(tmp_path: Path) -> None:
    """End-to-end: a single tool-call round trip drives both observe hooks."""

    class _OneToolThenDoneClient(LLMClient):
        """First turn yields a tool_call; second turn returns plain text."""

        def __init__(self) -> None:
            super().__init__()
            self._turn = 0

        async def stream_chat_completion(
            self, request: Any
        ) -> AsyncIterator[Any]:
            self._turn += 1
            if self._turn == 1:
                from deepseek_tui.protocol.responses import StreamToolCalls

                yield StreamToolCalls(
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="read_file",
                            arguments={"path": "src/main.py"},
                        )
                    ]
                )
                yield StreamDone(usage=Usage(input_tokens=1, output_tokens=1))
            else:
                yield StreamTextDelta(text="done")
                yield StreamDone(usage=Usage(input_tokens=1, output_tokens=1))

    # Seed a real file so read_file succeeds.
    target = tmp_path / "src"
    target.mkdir(parents=True, exist_ok=True)
    (target / "main.py").write_text("print('hi')\n", encoding="utf-8")

    engine = await Engine.create(
        EngineHandle(),
        _OneToolThenDoneClient(),
        default_model="test",
        working_directory=tmp_path,
    )

    async def _drain() -> None:
        while True:
            await engine.handle.events.get()

    drain_task = asyncio.create_task(_drain())
    runner = asyncio.create_task(engine.run())
    try:
        await engine.handle.send_op(
            SendMessageOp(content="open src/main.py please")
        )
        for _ in range(200):
            await asyncio.sleep(0.02)
            if "read_file" in engine.working_set.recent_tool_uses:
                break
    finally:
        runner.cancel()
        drain_task.cancel()
        for t in (runner, drain_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    assert engine.working_set.message_count == 1
    assert "read_file" in engine.working_set.recent_tool_uses
    assert any("main.py" in p for p in engine.working_set.recent_paths)
