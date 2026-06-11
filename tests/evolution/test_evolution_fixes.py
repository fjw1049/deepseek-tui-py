"""Tests for evolution audit fixes: evidence factory, risk, reject, scheduler, review retry."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_tui.evolution.constants import (
    CURATED_MEMORY_STORE_KEY,
    EVOLUTION_LEDGER_KEY,
    TURN_EVIDENCE_FACTORY_KEY,
    TURN_EVIDENCE_KEY,
    resolve_turn_evidence,
)
from deepseek_tui.evolution.curated.store import CuratedMemoryStore
from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.memory_curate_tool import MemoryCurateTool


# ---------------------------------------------------------------------------
# Fix 1: ProceduralSkillBackend risk assignment
# ---------------------------------------------------------------------------


def test_skill_backend_risk_levels() -> None:
    from deepseek_tui.evolution.backends.procedural_skill import ProceduralSkillBackend
    from deepseek_tui.evolution.procedural.skill_store import ProceduralSkillStore

    store = MagicMock(spec=ProceduralSkillStore)
    store.skill_root.return_value = Path("/tmp/skills/test")
    backend = ProceduralSkillBackend(store)

    mut_patch = backend.mutation_from_tool("skill_manage", {"action": "patch", "name": "x"})
    assert mut_patch is not None
    assert mut_patch.risk == "low"

    mut_create = backend.mutation_from_tool("skill_manage", {"action": "create", "name": "x"})
    assert mut_create is not None
    assert mut_create.risk == "medium"

    mut_delete = backend.mutation_from_tool("skill_manage", {"action": "delete", "name": "x"})
    assert mut_delete is not None
    assert mut_delete.risk == "high"

    mut_edit = backend.mutation_from_tool("skill_manage", {"action": "edit", "name": "x"})
    assert mut_edit is not None
    assert mut_edit.risk == "medium"

    mut_wf = backend.mutation_from_tool("skill_manage", {"action": "write_file", "name": "x"})
    assert mut_wf is not None
    assert mut_wf.risk == "medium"

    mut_rf = backend.mutation_from_tool("skill_manage", {"action": "remove_file", "name": "x"})
    assert mut_rf is not None
    assert mut_rf.risk == "medium"


# ---------------------------------------------------------------------------
# Fix 2: PeriodicTurnScheduler idle timeout
# ---------------------------------------------------------------------------


def test_scheduler_idle_timeout_fires() -> None:
    from deepseek_tui.post_turn.scheduler import PeriodicTurnScheduler

    sched = PeriodicTurnScheduler(every_n=100, idle_timeout_s=0.05, warmup_enabled=False)
    sched.notify("t1", "a")
    assert not sched.is_due("t1"), "count=1 < threshold=100"

    time.sleep(0.06)
    assert sched.is_due("t1"), "idle timeout should have fired"


def test_scheduler_idle_timeout_disabled_by_default() -> None:
    from deepseek_tui.post_turn.scheduler import PeriodicTurnScheduler

    sched = PeriodicTurnScheduler(every_n=100, warmup_enabled=False)
    sched.notify("t1", "a")
    assert not sched.is_due("t1")


def test_scheduler_idle_timeout_reset_clears() -> None:
    from deepseek_tui.post_turn.scheduler import PeriodicTurnScheduler

    sched = PeriodicTurnScheduler(every_n=100, idle_timeout_s=0.05, warmup_enabled=False)
    sched.notify("t1", "a")
    time.sleep(0.06)
    sched.reset("t1")
    assert not sched.is_due("t1"), "reset should clear idle state"


# ---------------------------------------------------------------------------
# Fix 3: Ledger.reject uses audit store mark_rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ledger_reject_uses_audit_mark_rejected(tmp_path: Path) -> None:
    from deepseek_tui.config.models import EvolutionConfig
    from deepseek_tui.evolution.audit.store import EvolutionAuditStore
    from deepseek_tui.evolution.backends.curated_memory import CuratedMemoryBackend
    from deepseek_tui.evolution.curated.store import CuratedMemoryStore
    from deepseek_tui.evolution.ledger import ExperienceLedger
    from deepseek_tui.evolution.policy import DefaultEvolutionPolicy
    from deepseek_tui.evolution.protocols import ExperienceMutation

    db_path = tmp_path / "state.db"
    audit = EvolutionAuditStore(db_path)
    await audit.initialize()
    store = CuratedMemoryStore(tmp_path / "memories")
    backend = CuratedMemoryBackend(store)

    cfg = EvolutionConfig()
    cfg.ledger.skill_create = "propose"
    ledger = ExperienceLedger(
        policy=DefaultEvolutionPolicy(cfg),
        audit=audit,
        backends=[backend],
    )
    evidence = TurnEvidence(
        thread_id="t1",
        user_text="test",
        workspace=str(tmp_path),
        messages=[],
        had_tool_calls=False,
        success=True,
    )
    record = await ledger.submit(
        ExperienceMutation(
            kind="skill_create",
            payload={"action": "create", "name": "test-skill", "content": "x"},
            risk="medium",
        ),
        source="review",
        evidence=evidence,
    )
    assert record.status == "proposed"

    rejected = await ledger.reject(record.id, reason="not wanted")
    assert rejected is not None
    assert rejected.status == "rejected"
    assert rejected.reason == "not wanted"


# ---------------------------------------------------------------------------
# Fix 4: TurnEvidence factory — resolve_turn_evidence
# ---------------------------------------------------------------------------


def test_resolve_turn_evidence_prefers_factory() -> None:
    static = TurnEvidence(
        thread_id="t-static",
        user_text="old",
        workspace="/tmp",
        messages=[],
        had_tool_calls=False,
        success=False,
    )
    live = TurnEvidence(
        thread_id="t-live",
        user_text="new",
        workspace="/tmp",
        messages=[{"role": "user", "content": "new"}],
        had_tool_calls=True,
        success=True,
    )
    metadata: dict = {
        TURN_EVIDENCE_KEY: static,
        TURN_EVIDENCE_FACTORY_KEY: lambda: live,
    }
    result = resolve_turn_evidence(metadata)
    assert result is not None
    assert result.thread_id == "t-live"
    assert result.success is True


def test_resolve_turn_evidence_falls_back_to_static() -> None:
    static = TurnEvidence(
        thread_id="t-static",
        user_text="hello",
        workspace="/tmp",
        messages=[],
        had_tool_calls=False,
        success=True,
    )
    metadata: dict = {TURN_EVIDENCE_KEY: static}
    result = resolve_turn_evidence(metadata)
    assert result is not None
    assert result.thread_id == "t-static"


def test_resolve_turn_evidence_returns_none_when_empty() -> None:
    assert resolve_turn_evidence({}) is None


@pytest.mark.asyncio
async def test_memory_curate_uses_factory_when_no_static_evidence(tmp_path: Path) -> None:
    """Tool should use evidence factory when static TURN_EVIDENCE_KEY is absent."""
    store = CuratedMemoryStore(tmp_path)
    ledger_stub = MagicMock()
    ledger_stub.submit = AsyncMock(
        return_value=SimpleNamespace(
            id="rec-1", status="applied", kind="memory_curate_add", reason=""
        )
    )
    live_evidence = TurnEvidence(
        thread_id="t-factory",
        user_text="from factory",
        workspace=str(tmp_path),
        messages=[{"role": "user", "content": "from factory"}],
        had_tool_calls=True,
        success=True,
        turn_id="turn-factory",
    )
    ctx = ToolContext(working_directory=tmp_path)
    from .service_context import add_named_service

    add_named_service(ctx, CURATED_MEMORY_STORE_KEY, store)
    add_named_service(ctx, EVOLUTION_LEDGER_KEY, ledger_stub)
    ctx.metadata[TURN_EVIDENCE_FACTORY_KEY] = lambda: live_evidence

    result = await MemoryCurateTool().execute(
        {"action": "add", "target": "memory", "content": "note"},
        ctx,
    )
    assert result.success
    ledger_stub.submit.assert_called_once()
    _, kwargs = ledger_stub.submit.call_args
    assert kwargs["evidence"].turn_id == "turn-factory"
    assert kwargs["evidence"].success is True


# ---------------------------------------------------------------------------
# Fix 5: Review retry + failure notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_retries_on_failure() -> None:
    """_run_review retries once and then emits a failure status."""
    from unittest.mock import patch

    from deepseek_tui.evolution.pipeline import EvolutionPipeline

    evidence = TurnEvidence(
        thread_id="t-retry",
        user_text="test",
        workspace="/tmp",
        messages=[],
        had_tool_calls=False,
        success=True,
    )

    review_calls: list[int] = []

    async def _failing_review(*args, **kwargs):
        review_calls.append(1)
        raise RuntimeError("LLM call failed")

    emitted: list[object] = []

    async def _capture_emit(event: object) -> None:
        emitted.append(event)

    pipeline = object.__new__(EvolutionPipeline)
    pipeline._client = MagicMock()
    pipeline._review_model = "test"
    pipeline._backends = []
    pipeline._ledger = MagicMock()
    pipeline._review_max_steps = 4
    pipeline._workspace = Path("/tmp")
    pipeline.curated_store = MagicMock()
    pipeline.skill_store = MagicMock()
    pipeline._emit_event = _capture_emit

    with patch(
        "deepseek_tui.evolution.pipeline.run_evolution_review",
        side_effect=RuntimeError("LLM failed"),
    ):
        await pipeline._run_review(
            evidence, review_memory=True, review_skill=False
        )

    assert len(emitted) == 1
    from deepseek_tui.engine.events import StatusEvent

    assert isinstance(emitted[0], StatusEvent)
    assert "failed" in emitted[0].message.lower()


@pytest.mark.asyncio
async def test_review_emits_status_on_exhausted_retries() -> None:
    from deepseek_tui.evolution.pipeline import EvolutionPipeline

    emitted: list[object] = []

    async def _capture_emit(event: object) -> None:
        emitted.append(event)

    pipeline = object.__new__(EvolutionPipeline)
    pipeline._emit_event = _capture_emit

    await pipeline._emit_review_failure("t-test")

    assert len(emitted) == 1
    from deepseek_tui.engine.events import StatusEvent

    assert isinstance(emitted[0], StatusEvent)
    assert "failed" in emitted[0].message.lower()
