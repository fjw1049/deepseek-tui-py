from pathlib import Path

import pytest

from deepseek_tui.config.models import EvolutionConfig
from deepseek_tui.evolution.audit.store import EvolutionAuditStore
from deepseek_tui.evolution.backends.curated_memory import CuratedMemoryBackend
from deepseek_tui.evolution.curated.store import CuratedMemoryStore
from deepseek_tui.evolution.ledger import ExperienceLedger
from deepseek_tui.evolution.policy import DefaultEvolutionPolicy
from deepseek_tui.evolution.protocols import ExperienceMutation
from deepseek_tui.post_turn.evidence import TurnEvidence


@pytest.mark.asyncio
async def test_ledger_auto_applies_memory_curate(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    audit = EvolutionAuditStore(db_path)
    await audit.initialize()
    store = CuratedMemoryStore(tmp_path / "memories")
    backend = CuratedMemoryBackend(store)
    ledger = ExperienceLedger(
        policy=DefaultEvolutionPolicy(EvolutionConfig()),
        audit=audit,
        backends=[backend],
    )
    evidence = TurnEvidence(
        thread_id="t1",
        user_text="note",
        workspace=str(tmp_path),
        messages=[],
        had_tool_calls=False,
        success=True,
    )
    record = await ledger.submit(
        ExperienceMutation(
            kind="memory_curate_add",
            payload={"action": "add", "target": "memory", "content": "persist me"},
            target_path=str(store.memory_path),
            risk="low",
        ),
        source="main_tool",
        evidence=evidence,
    )
    assert record.status in ("pending_apply", "applied")
    updated = await audit.get(record.id)
    assert updated is not None
    assert updated.status == "applied"
    assert "persist me" in store.memory_path.read_text(encoding="utf-8")
