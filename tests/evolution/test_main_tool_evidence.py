"""Main-agent evolution tools require live turn evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.evolution.constants import (
    CURATED_MEMORY_STORE_KEY,
    EVOLUTION_LEDGER_KEY,
    TURN_EVIDENCE_KEY,
)
from deepseek_tui.evolution.curated.store import CuratedMemoryStore
from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.tools.context import ToolContext
from .service_context import add_named_service
from deepseek_tui.tools.memory_curate_tool import MemoryCurateTool


def _evidence(thread_id: str = "t1", turn_id: str = "turn-a") -> TurnEvidence:
    return TurnEvidence(
        thread_id=thread_id,
        user_text="hello",
        workspace="/tmp/ws",
        messages=[{"role": "user", "content": "hello"}],
        had_tool_calls=False,
        success=True,
        turn_id=turn_id,
        user_turn_index=1,
    )


class _StubLedger:
    def __init__(self) -> None:
        self.submissions: list[tuple[object, str, TurnEvidence]] = []

    async def submit(self, mutation: object, *, source: str, evidence: TurnEvidence) -> object:
        from types import SimpleNamespace

        self.submissions.append((mutation, source, evidence))
        return SimpleNamespace(
            id="rec-1", status="applied", kind="memory_curate_add", reason=""
        )


@pytest.mark.asyncio
async def test_memory_curate_fails_without_turn_evidence(tmp_path: Path) -> None:
    store = CuratedMemoryStore(tmp_path)
    ctx = ToolContext(working_directory=tmp_path)
    add_named_service(ctx, CURATED_MEMORY_STORE_KEY, store)
    add_named_service(ctx, EVOLUTION_LEDGER_KEY, _StubLedger())

    result = await MemoryCurateTool().execute(
        {"action": "add", "target": "memory", "content": "note"},
        ctx,
    )
    assert not result.success
    assert "not available" in result.content


@pytest.mark.asyncio
async def test_memory_curate_uses_current_turn_evidence(tmp_path: Path) -> None:
    store = CuratedMemoryStore(tmp_path)
    ledger = _StubLedger()
    evidence = _evidence(turn_id="turn-current")
    ctx = ToolContext(working_directory=tmp_path)
    add_named_service(ctx, CURATED_MEMORY_STORE_KEY, store)
    add_named_service(ctx, EVOLUTION_LEDGER_KEY, ledger)
    ctx.metadata[TURN_EVIDENCE_KEY] = evidence

    result = await MemoryCurateTool().execute(
        {"action": "add", "target": "memory", "content": "note"},
        ctx,
    )
    assert result.success
    assert len(ledger.submissions) == 1
    _, source, submitted = ledger.submissions[0]
    assert source == "main_tool"
    assert submitted.turn_id == "turn-current"


@pytest.mark.asyncio
async def test_memory_curate_review_mode_requires_store(tmp_path: Path) -> None:
    ctx = ToolContext(working_directory=tmp_path)
    ctx.metadata["evolution_review_mode"] = True

    with pytest.raises(RuntimeError, match="curated memory store"):
        await MemoryCurateTool().execute(
            {"action": "add", "target": "memory", "content": "note"},
            ctx,
        )


@pytest.mark.asyncio
async def test_memory_curate_review_mode_with_store(tmp_path: Path) -> None:
    store = CuratedMemoryStore(tmp_path)
    ctx = ToolContext(working_directory=tmp_path)
    ctx.metadata["evolution_review_mode"] = True
    add_named_service(ctx, CURATED_MEMORY_STORE_KEY, store)

    result = await MemoryCurateTool().execute(
        {"action": "add", "target": "memory", "content": "note"},
        ctx,
    )
    assert result.success
    assert "review_only" in result.content
