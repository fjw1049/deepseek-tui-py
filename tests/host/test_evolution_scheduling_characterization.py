"""Characterization tests for evolution review scheduling and ledger events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.capabilities.evolution import create_evolution_runtime
from deepseek_tui.config.models import (
    Config,
    EvolutionConfig,
    EvolutionCuratedConfig,
    EvolutionLedgerConfig,
    StateConfig,
)
from deepseek_tui.engine.events import EvolutionProposalEvent
from deepseek_tui.evolution.pipeline import EvolutionPipeline, build_evolution_pipeline
from deepseek_tui.evolution.protocols import ExperienceMutation
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.gates import GateConfig
from deepseek_tui.post_turn.scheduler import PeriodicTurnScheduler


def _config(tmp_path: Path) -> Config:
    return Config(
        state=StateConfig(database_path=tmp_path / "state.db"),
        evolution=EvolutionConfig(
            enabled=True,
            mode="suggest",
            curated=EvolutionCuratedConfig(dir=str(tmp_path / "curated")),
            ledger=EvolutionLedgerConfig(skill_create="propose"),
        ),
    )


def _evidence(
    *,
    thread_id: str = "t1",
    user_text: str = "please review this longer user request",
    tool_rounds: int = 0,
) -> TurnEvidence:
    return TurnEvidence(
        thread_id=thread_id,
        user_text=user_text,
        workspace="/tmp/ws",
        messages=[{"role": "user", "content": user_text}],
        had_tool_calls=False,
        success=True,
        tool_rounds=tool_rounds,
        user_turn_index=1,
        turn_id="turn-1",
    )


def _pipeline_stub() -> EvolutionPipeline:
    pipeline = EvolutionPipeline.__new__(EvolutionPipeline)
    pipeline._enabled = True
    pipeline._current_thread_id = ""
    pipeline._review_memory_sched = PeriodicTurnScheduler(every_n=1, warmup_enabled=False)
    pipeline._skill_tool_rounds = defaultdict(int)
    pipeline._skill_nudge_tool_rounds = 100
    pipeline._gate_cfg = GateConfig(min_chars=1, skip_slash=False)
    pipeline._config = SimpleNamespace(
        evolution=SimpleNamespace(
            schedulers=SimpleNamespace(min_tool_calls_signal=99),
        ),
    )
    pipeline._review_turn_buffers = defaultdict(list)
    pipeline._review_tasks = set()
    return pipeline


def test_pipeline_main_tool_resets_memory_scheduler() -> None:
    pipeline = _pipeline_stub()
    pipeline._current_thread_id = "t1"
    pipeline._review_memory_sched.notify("t1", object())
    assert pipeline._review_memory_sched.count("t1") == 1

    pipeline.on_main_tool_called("memory_curate")

    assert pipeline._review_memory_sched.count("t1") == 0


def test_pipeline_main_tool_resets_skill_rounds() -> None:
    pipeline = _pipeline_stub()
    pipeline._current_thread_id = "t1"
    pipeline._skill_tool_rounds["t1"] = 7

    pipeline.on_main_tool_called("skill_manage")

    assert pipeline._skill_tool_rounds["t1"] == 0


@pytest.mark.asyncio
async def test_pipeline_after_turn_resets_scheduler_when_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _pipeline_stub()
    scheduled: list[object] = []

    def _capture_task(coro: object, **kwargs: object) -> MagicMock:
        scheduled.append(coro)
        task = MagicMock()
        task.add_done_callback = MagicMock()
        return task

    monkeypatch.setattr(asyncio, "create_task", _capture_task)
    monkeypatch.setattr(
        "deepseek_tui.evolution.pipeline.detect_signals",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "deepseek_tui.evolution.pipeline.should_review",
        lambda *_args, **_kwargs: True,
    )

    await pipeline.after_turn(_evidence())

    assert pipeline._review_memory_sched.count("t1") == 0
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_pipeline_after_turn_skips_review_when_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _pipeline_stub()
    pipeline._gate_cfg = GateConfig(min_chars=20, skip_slash=False)
    scheduled: list[object] = []

    def _capture_task(coro: object, **kwargs: object) -> MagicMock:
        scheduled.append(coro)
        task = MagicMock()
        task.add_done_callback = MagicMock()
        return task

    monkeypatch.setattr(asyncio, "create_task", _capture_task)
    monkeypatch.setattr(
        "deepseek_tui.evolution.pipeline.detect_signals",
        lambda *_args, **_kwargs: [],
    )

    await pipeline.after_turn(_evidence(user_text="hi"))

    assert len(scheduled) == 0


@pytest.mark.asyncio
async def test_proposed_mutation_emits_workbench_proposal_event(
    tmp_path: Path,
) -> None:
    emitted: list[object] = []

    async def _capture(event: object) -> None:
        emitted.append(event)

    cfg = _config(tmp_path)
    pipeline = build_evolution_pipeline(
        cfg,
        AsyncMock(),
        tmp_path,
        emit_event=_capture,
    )
    await pipeline.start()
    try:
        record = await pipeline.ledger.submit(
            ExperienceMutation(
                kind="skill_create",
                payload={"action": "create", "name": "test-skill", "content": "x"},
                risk="medium",
            ),
            source="review",
            evidence=_evidence(),
        )
        assert record.status == "proposed"
        assert len(emitted) == 1
        event = emitted[0]
        assert isinstance(event, EvolutionProposalEvent)
        assert event.record_id == record.id
        assert event.kind == "skill_create"
        assert event.summary == "skill create"
        assert event.asset_path is None
    finally:
        await pipeline.stop()


@pytest.mark.asyncio
async def test_create_evolution_runtime_wires_emit_event(tmp_path: Path) -> None:
    emitted: list[object] = []

    async def _capture(event: object) -> None:
        emitted.append(event)

    runtime = create_evolution_runtime(
        _config(tmp_path),
        AsyncMock(),
        ServiceRegistry(),
        workspace=tmp_path,
        emit_event=_capture,
    )
    assert runtime.pipeline is not None
    await runtime.pipeline.start()
    try:
        record = await runtime.pipeline.ledger.submit(
            ExperienceMutation(
                kind="skill_create",
                payload={"action": "create", "name": "runtime-skill", "content": "y"},
                risk="medium",
            ),
            source="review",
            evidence=_evidence(thread_id="runtime-thread"),
        )
        assert record.status == "proposed"
        assert len(emitted) == 1
        assert isinstance(emitted[0], EvolutionProposalEvent)
    finally:
        await runtime.pipeline.stop()
