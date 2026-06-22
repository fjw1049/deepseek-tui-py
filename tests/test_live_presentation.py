"""Live model smoke test for the task-narrative TUI projection.

Run explicitly with project credentials::

    uv run --extra dev pytest -m live tests/test_live_presentation.py -s -v
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import FeatureConfig
from deepseek_tui.tui.app import DeepSeekTUI
from deepseek_tui.tui.transcript import (
    Transcript,
    _ActionBatchCell,
    _AssistantCell,
    _IntentCell,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.live
async def test_real_model_renders_intent_batch_and_final_answer() -> None:
    cfg = ConfigLoader().load(workspace=PROJECT_ROOT).model_copy(deep=True)
    provider = cfg.effective_provider_config()
    if not (cfg.api_key or provider.api_key):
        pytest.skip("no API key configured")
    cfg.features = FeatureConfig(
        tasks=False,
        subagents=False,
        mcp=False,
        automations=False,
    )
    app = DeepSeekTUI(config=cfg)
    prompt = (
        "请先用一句中文说明你准备做什么，然后在同一轮并行调用 read_file，分别读取 "
        "pyproject.toml、src/deepseek_tui/engine/events.py、"
        "src/deepseek_tui/tui/transcript.py。不要调用其他工具。读取后简短总结，"
        "并在最终回答中包含 PRESENTATION_LIVE_OK。"
    )

    try:
        async with app.run_test(size=(120, 50)) as pilot:
            startup_deadline = time.monotonic() + 45
            while app._engine is None and time.monotonic() < startup_deadline:
                await pilot.pause()
                await asyncio.sleep(0.1)
            assert app._engine is not None, "TUI engine did not start"

            await app._submit_user_message(prompt)
            turn_deadline = time.monotonic() + 90
            saw_active = False
            while time.monotonic() < turn_deadline:
                active = app.handle.is_turn_active()
                saw_active = saw_active or active
                if saw_active and not active:
                    break
                await pilot.pause()
                await asyncio.sleep(0.1)
            assert saw_active, "engine never started the live turn"
            assert not app.handle.is_turn_active(), "live turn timed out"
            await pilot.pause()

            transcript = app.query_one(Transcript)
            intents = list(transcript.query(_IntentCell))
            batches = list(transcript.query(_ActionBatchCell))
            batched_actions = [action for batch in batches for action in batch.actions]
            assistant_text = "\n".join(
                cell.content_text for cell in transcript.query(_AssistantCell)
            )
            print(
                "presentation_live",
                {
                    "intent_cells": len(intents),
                    "batch_cells": len(batches),
                    "batched_actions": len(batched_actions),
                    "final_marker": "PRESENTATION_LIVE_OK" in assistant_text,
                },
            )
            assert intents, "expected a visible intent narration"
            assert batches, "expected three parallel reads to collapse into one batch"
            assert len(batched_actions) == 3
            assert {action.tool_name for action in batched_actions} == {"read_file"}
            assert "PRESENTATION_LIVE_OK" in assistant_text
    finally:
        if app._engine is not None:
            await app._engine.shutdown()
