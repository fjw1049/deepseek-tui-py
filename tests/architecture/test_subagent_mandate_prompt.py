"""Sub-agent mandate prompt compatibility tests."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.engine.subagent_intent import SUBAGENT_MANDATE_BLOCK
from deepseek_tui.prompts import AppMode


def test_subagent_mandate_block_is_injected(tmp_path: Path) -> None:
    prompt = build_system_prompt(
        None,
        mode=AppMode.AGENT,
        workspace=tmp_path,
        project_context_enabled=False,
        subagent_mandate=True,
    )
    assert SUBAGENT_MANDATE_BLOCK in prompt
