"""Integration-style tests for evolution without a live LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, EvolutionConfig
from deepseek_tui.evolution.constants import (
    CURATED_MEMORY_STORE_KEY,
    EVOLUTION_LEDGER_KEY,
    TURN_EVIDENCE_KEY,
)
from deepseek_tui.evolution.pipeline import build_evolution_pipeline
from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.evolution.constants import SKILL_STORE_KEY
from deepseek_tui.tools.context import ToolContext
from .service_context import add_named_service
from deepseek_tui.tools.memory_curate_tool import MemoryCurateTool
from deepseek_tui.tools.skill_manage_tool import SkillManageTool

_SKILL = """---
name: flow-skill
description: Integration test skill
---
# Flow skill
"""


@pytest.mark.asyncio
async def test_memory_curate_end_to_end_via_tool(tmp_path: Path) -> None:
    cfg = Config()
    cfg.evolution.enabled = True
    cfg.evolution.curated.memory_char_limit = 200
    pipeline = build_evolution_pipeline(cfg, client=object(), workspace=tmp_path)  # type: ignore[arg-type]
    store = pipeline.curated_store
    ledger = pipeline.ledger
    evidence = TurnEvidence(
        thread_id="thread-int",
        user_text="remember this",
        workspace=str(tmp_path),
        messages=[{"role": "user", "content": "remember this"}],
        had_tool_calls=False,
        success=True,
        turn_id="turn-1",
    )
    ctx = ToolContext(working_directory=tmp_path)
    add_named_service(ctx, CURATED_MEMORY_STORE_KEY, store)
    add_named_service(ctx, EVOLUTION_LEDGER_KEY, ledger)
    ctx.metadata[TURN_EVIDENCE_KEY] = evidence

    tool = MemoryCurateTool()
    ok = await tool.execute(
        {"action": "add", "target": "memory", "content": "durable project fact"},
        ctx,
    )
    assert ok.success
    assert "durable project fact" in store.memory_path.read_text(encoding="utf-8")

    overflow = await tool.execute(
        {"action": "add", "target": "memory", "content": "x" * 300},
        ctx,
    )
    assert not overflow.success
    assert "usage" in overflow.content or "exceed" in overflow.content.lower()


@pytest.mark.asyncio
async def test_skill_manage_patch_supporting_file_via_tool(tmp_path: Path) -> None:
    cfg = Config()
    cfg.evolution.enabled = True
    cfg.evolution.ledger.skill_create = "auto"
    cfg.evolution.ledger.skill_patch = "auto"
    pipeline = build_evolution_pipeline(cfg, client=object(), workspace=tmp_path)  # type: ignore[arg-type]
    store = pipeline.skill_store
    ledger = pipeline.ledger
    evidence = TurnEvidence(
        thread_id="thread-int",
        user_text="skill",
        workspace=str(tmp_path),
        messages=[],
        had_tool_calls=True,
        success=True,
        turn_id="turn-2",
    )
    ctx = ToolContext(working_directory=tmp_path)
    add_named_service(ctx, CURATED_MEMORY_STORE_KEY, pipeline.curated_store)
    add_named_service(ctx, EVOLUTION_LEDGER_KEY, ledger)
    add_named_service(ctx, SKILL_STORE_KEY, store)
    ctx.metadata[TURN_EVIDENCE_KEY] = evidence

    created = store.create("flow-skill", _SKILL)
    assert created.ok
    written = store.write_file("flow-skill", "notes.txt", "step one")
    assert written.ok

    patch = await SkillManageTool().execute(
        {
            "action": "patch",
            "name": "flow-skill",
            "file_path": "notes.txt",
            "old_string": "step one",
            "new_string": "step two",
        },
        ctx,
    )
    assert patch.success
    notes = store.skill_root("flow-skill") / "notes.txt"
    assert notes.read_text(encoding="utf-8") == "step two"


@pytest.mark.asyncio
async def test_pipeline_builds_with_evolution_enabled(tmp_path: Path) -> None:
    cfg = Config()
    cfg.evolution = EvolutionConfig(enabled=True)
    pipeline = build_evolution_pipeline(cfg, client=object(), workspace=tmp_path)  # type: ignore[arg-type]
    assert pipeline.ledger is not None
    assert pipeline.curated_store is not None
