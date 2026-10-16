"""An idle background completion must run as a runtime-owned turn.

A ``run_in_background`` child that finishes after its parent turn ended makes
the engine deliver the result in a hidden follow-up turn. When the engine
queued that turn on its own, the runtime never opened a turn record or a
monitor for it, so its events sat in the handle queue until the next user turn.
That turn's monitor then read the stale ``TurnCompleteEvent`` as its own end.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import SUBAGENT_BACKGROUND_DONE_KIND
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta
from deepseek_tui.server.app import build_fastapi_app
from deepseek_tui.server.runtime import AppRuntime
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    StartTurnRequest,
    TurnItemKind,
)
from deepseek_tui.tools.subagent import SubAgentAssignment, SubAgentCompletion, SubAgentType
from deepseek_tui.tools.subagent.agent import SubAgent
from deepseek_tui.tools.subagent.types import SubAgentStatus

_TERMINAL = {
    RuntimeTurnStatus.COMPLETED,
    RuntimeTurnStatus.FAILED,
    RuntimeTurnStatus.INTERRUPTED,
}


class _ReplyByPrompt(LLMClient):
    """Answers by what the last user message asks, whatever else calls it."""

    def __init__(self) -> None:
        super().__init__()
        self.answered: list[str] = []

    async def stream_chat_completion(self, request):  # noqa: ANN001, ANN201
        last = request.messages[-1].text_content() if request.messages else ""
        if "background done" in last:
            reply = "background reply"
        elif "user question" in last:
            reply = "user answer"
        else:
            reply = "title"
        self.answered.append(reply)
        yield StreamTextDelta(text=reply)
        yield StreamDone()


@pytest.fixture
def subagent_runtime_app(runtime_data_dir: Path) -> object:
    config = Config(
        features=FeatureConfig(mcp=False, tasks=False, subagents=True, automations=False)
    )
    runtime = AppRuntime(config=config, working_directory=runtime_data_dir)
    return build_fastapi_app(runtime, http_mode=True, insecure_no_auth=True)


async def _until(predicate, timeout: float = 10.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.02)


def _agent_texts(manager, turn_id: str) -> list[str]:  # noqa: ANN001
    return [
        item.detail or item.summary or ""
        for item in manager.store.list_items_for_turn(turn_id)
        if item.kind == TurnItemKind.AGENT_MESSAGE
    ]


@pytest.mark.parametrize("during_cleanup", [False, True])
async def test_idle_background_completion_runs_in_its_own_turn(
    subagent_runtime_app: object, monkeypatch, during_cleanup,
) -> None:
    manager = subagent_runtime_app.state.thread_manager  # type: ignore[attr-defined]
    client = _ReplyByPrompt()
    manager._llm_client = client  # noqa: SLF001
    thread = await manager.create_thread(CreateThreadRequest())
    await manager._ensure_engine_loaded(thread)  # noqa: SLF001
    engine = manager._active[thread.id].engine  # noqa: SLF001
    release_cleanup = asyncio.Event()
    if during_cleanup:
        cleanup_started = asyncio.Event()
        async def finish_capture(*args, **kwargs):
            cleanup_started.set()
            await release_cleanup.wait()
        monkeypatch.setattr(manager.browser_service, "end_agent_capture", finish_capture)
        await manager.start_turn(thread.id, StartTurnRequest(prompt="user question"))
        await asyncio.wait_for(cleanup_started.wait(), 5)
        await _until(lambda: not engine.handle.is_turn_active())
    try:
        # A background child finishes while the thread has no active turn.
        subagents = engine.tool_context.subagent_manager
        child = SubAgent(
            agent_type=SubAgentType.EXPLORE,
            prompt="look around",
            assignment=SubAgentAssignment(objective="look around"),
            model="deepseek-chat",
            nickname=None,
            allowed_tools=None,
            session_boot_id=subagents.session_boot_id,
            workspace=Path(thread.workspace),
            background=True,
        )
        child.status = SubAgentStatus.completed()
        child.result = "### SUMMARY\nfound 3 files"
        subagents._agents[child.id] = child  # noqa: SLF001
        engine._enqueue_subagent_completion(  # noqa: SLF001
            SubAgentCompletion(agent_id=child.id, payload="background done")
        )
        if during_cleanup:
            await asyncio.sleep(0.1)
            assert "background reply" not in client.answered
            release_cleanup.set()
        await _until(lambda: "background reply" in client.answered)

        def hidden_turns() -> list:  # noqa: ANN202
            return [
                t for t in manager.store.list_turns_for_thread(thread.id)
                if t.input_summary == SUBAGENT_BACKGROUND_DONE_KIND
            ]

        await _until(lambda: bool(hidden_turns()) and hidden_turns()[0].status in _TERMINAL)
        await _until(lambda: not manager._thread_has_active_turn(thread.id))  # noqa: SLF001
        assert _agent_texts(manager, hidden_turns()[0].id) == ["background reply"]

        # The user's next turn sees only its own answer.
        turn = await manager.start_turn(thread.id, StartTurnRequest(prompt="user question"))
        await _until(lambda: manager.store.load_turn(turn.id).status in _TERMINAL)
        assert _agent_texts(manager, turn.id) == ["user answer"]
    finally:
        release_cleanup.set()
        await manager.aclose()


async def test_internal_delivery_waits_for_previous_turn_cleanup(runtime_app, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from deepseek_tui.engine.handle import EngineHandle, PROCESS_BACKGROUND_DONE_KIND

    manager = runtime_app.state.thread_manager
    handle = EngineHandle()
    state = SimpleNamespace(handle=handle, engine=SimpleNamespace(mode="agent"), active_turn=object())
    manager._active["cleanup"] = state
    release = asyncio.Event()

    async def cleanup():
        await release.wait()
        state.active_turn = None

    monitor = asyncio.create_task(cleanup())
    manager._thread_lease_owners["cleanup"] = monitor
    start = AsyncMock()
    monkeypatch.setattr(manager, "start_turn", start)
    delivery = asyncio.create_task(manager._start_internal_turn("cleanup", "done", PROCESS_BACKGROUND_DONE_KIND))
    try:
        await asyncio.sleep(0)
        start.assert_not_awaited()
        release.set()
        assert await asyncio.wait_for(delivery, 2)
        start.assert_awaited_once()
    finally:
        release.set()
        await monitor
        if not delivery.done():
            delivery.cancel()
        await asyncio.gather(delivery, return_exceptions=True)
        manager._active.pop("cleanup", None)
        manager._thread_lease_owners.pop("cleanup", None)
