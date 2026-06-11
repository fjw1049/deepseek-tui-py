from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.capabilities.evolution import (
    attach_evolution_bindings,
    build_main_tool_evolution_response,
    create_evolution_runtime,
    evolution_action_response,
    evolution_decision_from_record_status,
    evolution_record_to_dict,
    publish_turn_evidence,
)
from deepseek_tui.config.models import Config, EvolutionConfig, EvolutionCuratedConfig, StateConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.evolution.constants import (
    CURATED_MEMORY_STORE_KEY,
    EVOLUTION_LEDGER_KEY,
    SKILL_STORE_KEY,
    TURN_EVIDENCE_FACTORY_KEY,
    TURN_EVIDENCE_KEY,
)
from deepseek_tui.evolution.pipeline import EvolutionPipeline
from deepseek_tui.host.services import ServiceRegistry, ServiceScope


class _PipelineNoteRecorder:
    def __init__(self) -> None:
        self.thread_ids: list[str] = []

    def note_active_turn(self, thread_id: str) -> None:
        self.thread_ids.append(thread_id)


def _config(tmp_path: Path, *, enabled: bool) -> Config:
    return Config(
        state=StateConfig(database_path=tmp_path / "state.db"),
        evolution=EvolutionConfig(
            enabled=enabled,
            curated=EvolutionCuratedConfig(dir=str(tmp_path / "curated")),
        ),
    )


def test_evolution_capability_skips_when_disabled(tmp_path: Path) -> None:
    services = ServiceRegistry()

    runtime = create_evolution_runtime(
        _config(tmp_path, enabled=False),
        AsyncMock(),
        services,
        workspace=tmp_path,
        emit_event=None,
    )
    metadata: dict[str, object] = {}
    attach_evolution_bindings(runtime, services=services)

    assert runtime.pipeline is None
    assert runtime.curated_snapshot is None
    assert metadata == {}
    assert services.optional(EvolutionPipeline) is None


def test_evolution_capability_creates_pipeline_and_legacy_bindings(
    tmp_path: Path,
) -> None:
    services = ServiceRegistry()

    runtime = create_evolution_runtime(
        _config(tmp_path, enabled=True),
        AsyncMock(),
        services,
        workspace=tmp_path,
        emit_event=None,
    )
    metadata: dict[str, object] = {}
    attach_evolution_bindings(runtime, services=services)

    assert isinstance(runtime.pipeline, EvolutionPipeline)
    assert services.require(EvolutionPipeline) is runtime.pipeline
    assert metadata == {}
    assert services.require_named(CURATED_MEMORY_STORE_KEY) is runtime.pipeline.curated_store
    assert services.require_named(SKILL_STORE_KEY) is runtime.pipeline.skill_store
    assert services.require_named(EVOLUTION_LEDGER_KEY) is runtime.pipeline.ledger


@pytest.mark.asyncio
async def test_engine_create_evolution_uses_capability_bindings(tmp_path: Path) -> None:
    engine = await Engine.create(
        handle=EngineHandle(),
        client=AsyncMock(),
        config=_config(tmp_path, enabled=True),
        working_directory=tmp_path,
        start_mcp=False,
    )
    try:
        assert isinstance(engine._evolution_pipeline, EvolutionPipeline)
        assert EVOLUTION_LEDGER_KEY not in engine.tool_context.metadata
        assert engine.tool_context.services.require_named(EVOLUTION_LEDGER_KEY) is (
            engine._evolution_pipeline.ledger
        )
        assert engine.tool_context.services.require(EvolutionPipeline) is (
            engine._evolution_pipeline
        )
    finally:
        await engine.shutdown_session()


def test_evolution_capability_publish_turn_evidence_live_and_final() -> None:
    metadata: dict[str, object] = {}
    services = ServiceRegistry()
    services.add_named(
        EVOLUTION_LEDGER_KEY,
        object(),
        owner="test",
        scope=ServiceScope.ENGINE,
    )
    pipeline = _PipelineNoteRecorder()
    live_evidence = object()
    final_evidence = object()

    publish_turn_evidence(
        metadata=metadata,
        services=services,
        pipeline=pipeline,
        evidence=live_evidence,
        live_evidence_factory=lambda: live_evidence,
        final=False,
        thread_id="thread-1",
    )

    assert TURN_EVIDENCE_KEY not in metadata
    assert metadata[TURN_EVIDENCE_FACTORY_KEY]() is live_evidence  # type: ignore[operator]
    assert pipeline.thread_ids == ["thread-1"]

    publish_turn_evidence(
        metadata=metadata,
        services=services,
        pipeline=pipeline,
        evidence=final_evidence,
        live_evidence_factory=None,
        final=True,
        thread_id="thread-1",
    )

    assert metadata[TURN_EVIDENCE_KEY] is final_evidence
    assert TURN_EVIDENCE_FACTORY_KEY not in metadata
    assert pipeline.thread_ids == ["thread-1", "thread-1"]


def test_evolution_capability_publish_turn_evidence_noops_without_ledger() -> None:
    metadata: dict[str, object] = {}
    pipeline = _PipelineNoteRecorder()

    publish_turn_evidence(
        metadata=metadata,
        pipeline=pipeline,
        evidence=object(),
        live_evidence_factory=lambda: object(),
        final=False,
        thread_id="thread-1",
    )

    assert metadata == {}
    assert pipeline.thread_ids == []


def test_evolution_capability_builds_action_response() -> None:
    @dataclass
    class _Record:
        id: str
        status: str

    record = _Record(id="r1", status="applied")
    assert evolution_action_response(record) == {
        "ok": True,
        "record": {"id": "r1", "status": "applied"},
    }


def test_evolution_capability_serializes_records() -> None:
    @dataclass
    class _Record:
        id: str
        status: str

    assert evolution_record_to_dict(_Record(id="r1", status="pending")) == {
        "id": "r1",
        "status": "pending",
    }
    assert evolution_record_to_dict("plain") == {"repr": "'plain'"}


def test_evolution_capability_builds_main_tool_response() -> None:
    record = SimpleNamespace(
        id="rec-1",
        status="applied",
        kind="skill_manage_patch",
    )

    assert evolution_decision_from_record_status("applied") == "auto"
    payload = build_main_tool_evolution_response(
        record=record,
        decision="auto",
    )

    assert payload["ok"] is True
    assert payload["record_id"] == "rec-1"
    assert payload["kind"] == "skill_manage_patch"
