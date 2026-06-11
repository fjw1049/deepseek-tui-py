"""Characterization tests for memory capture/flush trigger dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.app_server.thread_manager import RuntimeThreadManager
from deepseek_tui.capabilities.memory import (
    build_flush_evidence,
    build_turn_evidence,
)
from deepseek_tui.capabilities.post_turn import (
    build_post_turn_pipelines,
    flush_post_turn_before_loss,
    run_post_turn_after_turn,
    start_post_turn_orchestrator,
    stop_post_turn_orchestrator,
)
from deepseek_tui.config.models import Config, MemoryConfig, MemorySmartConfig, PostTurnConfig
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.orchestrator import PostTurnOrchestrator
from deepseek_tui.protocol.messages import Message


class _RecordingPipeline:
    name = "rec"

    def __init__(self) -> None:
        self.after: list[TurnEvidence] = []
        self.flush: list[TurnEvidence] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def after_turn(self, evidence: TurnEvidence) -> None:
        self.after.append(evidence)

    async def flush_before_loss(self, evidence: TurnEvidence) -> None:
        self.flush.append(evidence)


class _CaptureCoordinator(MemoryCoordinator):
    def __init__(self) -> None:
        self.captures: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    async def capture_after_turn(self, *, thread_id: str, **kwargs: object) -> None:
        self.captures.append(thread_id)


@pytest.mark.asyncio
async def test_run_post_turn_after_turn_orchestrator_skips_direct_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_capture_calls: list[object] = []

    async def _capture(*_args: object) -> None:
        direct_capture_calls.append(True)

    monkeypatch.setattr(
        "deepseek_tui.capabilities.memory.capture_memory_after_turn",
        _capture,
    )
    post_turn = MagicMock()
    post_turn.after_turn = AsyncMock()
    evidence = object()

    await run_post_turn_after_turn(
        post_turn=post_turn,
        evidence=evidence,
        memory_coordinator=object(),
    )

    post_turn.after_turn.assert_awaited_once_with(evidence)
    assert direct_capture_calls == []


@pytest.mark.asyncio
async def test_run_post_turn_after_turn_fallback_captures_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    coordinator = _CaptureCoordinator()
    evidence = build_turn_evidence(
        thread_id="thread-1",
        user_text="remember this detail",
        workspace=tmp_path,
        turn_slice=[Message.user("remember this detail")],
        success=True,
        tool_rounds=0,
        user_turn_index=1,
        turn_id="turn-1",
    )

    await run_post_turn_after_turn(
        post_turn=None,
        evidence=evidence,
        memory_coordinator=coordinator,
    )

    assert coordinator.captures == ["thread-1"]


@pytest.mark.asyncio
async def test_run_post_turn_after_turn_no_op_without_evidence() -> None:
    post_turn = MagicMock()
    post_turn.after_turn = AsyncMock()

    await run_post_turn_after_turn(
        post_turn=post_turn,
        evidence=None,
        memory_coordinator=object(),
    )

    post_turn.after_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_pipeline_capture_once_via_orchestrator(
    tmp_path: Path,
) -> None:
    coordinator = _CaptureCoordinator()
    cfg = Config(
        post_turn=PostTurnConfig(enabled=True),
        memory=MemoryConfig(
            enabled=True,
            smart=MemorySmartConfig(
                enabled=True,
                capture_min_user_chars=1,
            ),
        ),
    )
    pipelines = build_post_turn_pipelines(
        cfg,
        memory_coordinator=coordinator,
        evolution_pipeline=None,
    )
    orchestrator = await start_post_turn_orchestrator(cfg, pipelines)
    assert isinstance(orchestrator, PostTurnOrchestrator)

    evidence = build_turn_evidence(
        thread_id="thread-1",
        user_text="remember this detail",
        workspace=tmp_path,
        turn_slice=[Message.user("remember this detail")],
        success=True,
        tool_rounds=0,
        user_turn_index=1,
        turn_id="turn-1",
    )
    try:
        await run_post_turn_after_turn(
            post_turn=orchestrator,
            evidence=evidence,
            memory_coordinator=coordinator,
        )
        assert coordinator.captures == ["thread-1"]
    finally:
        await stop_post_turn_orchestrator(orchestrator)


@pytest.mark.asyncio
async def test_compaction_flush_dispatch_passes_flush_mode_evidence(
    tmp_path: Path,
) -> None:
    pipeline = _RecordingPipeline()
    orchestrator = PostTurnOrchestrator([pipeline], flush_timeout_s=1.0)
    messages = [Message.user("long conversation"), Message.assistant("ok")]
    flush_evidence = build_flush_evidence(
        messages=messages,
        thread_id="thread-1",
        workspace=tmp_path,
        user_turn_index=2,
        turn_id="turn-2",
    )
    assert isinstance(flush_evidence, TurnEvidence)
    assert flush_evidence.flush_mode is True

    await flush_post_turn_before_loss(post_turn=orchestrator, evidence=flush_evidence)

    assert len(pipeline.flush) == 1
    assert pipeline.flush[0].flush_mode is True
    assert pipeline.flush[0].thread_id == "thread-1"


@pytest.mark.asyncio
async def test_flush_post_turn_before_loss_no_op_without_orchestrator_or_evidence() -> None:
    post_turn = MagicMock()
    post_turn.flush_before_loss = AsyncMock()
    evidence = object()

    await flush_post_turn_before_loss(post_turn=None, evidence=evidence)
    await flush_post_turn_before_loss(post_turn=post_turn, evidence=None)

    post_turn.flush_before_loss.assert_not_awaited()


@pytest.mark.asyncio
async def test_flush_engine_memory_coordinator_fallback_without_post_turn() -> None:
    mgr = RuntimeThreadManager.__new__(RuntimeThreadManager)
    coordinator = MagicMock(spec=MemoryCoordinator)
    coordinator.flush_session = AsyncMock()
    engine = MagicMock()
    engine.post_turn = None
    engine.memory_coordinator = coordinator
    engine.session_messages = [MagicMock()]

    await mgr._flush_engine_memory(engine, "evicted-thread")

    coordinator.flush_session.assert_awaited_once_with("evicted-thread")


@pytest.mark.asyncio
async def test_flush_engine_memory_coordinator_fallback_without_session_messages() -> None:
    mgr = RuntimeThreadManager.__new__(RuntimeThreadManager)
    post_turn = MagicMock()
    post_turn.flush_before_loss = AsyncMock()
    coordinator = MagicMock(spec=MemoryCoordinator)
    coordinator.flush_session = AsyncMock()
    engine = MagicMock()
    engine.post_turn = post_turn
    engine.memory_coordinator = coordinator
    engine.session_messages = []

    await mgr._flush_engine_memory(engine, "evicted-thread")

    post_turn.flush_before_loss.assert_not_awaited()
    coordinator.flush_session.assert_awaited_once_with("evicted-thread")
