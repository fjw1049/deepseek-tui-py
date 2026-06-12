"""Golden-style characterization for assembled system prompt output."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.prompts import AppMode, Personality


def test_agent_prompt_contains_core_sections_without_disk_io() -> None:
    prompt = build_system_prompt(
        mode=AppMode.AGENT,
        personality=Personality.CALM,
        workspace=Path("/tmp/workspace"),
        project_context_enabled=False,
        subagent_mandate=False,
        memory_enabled=False,
        evolution_enabled=False,
        workflow_guidelines=False,
    )

    assert prompt.startswith("You are DeepSeek TUI")
    assert "## Environment" in prompt
    assert "/tmp/workspace" in prompt


def test_plan_prompt_is_shorter_than_agent_prompt() -> None:
    agent = build_system_prompt(
        mode=AppMode.AGENT,
        workspace=Path("/tmp/workspace"),
        project_context_enabled=False,
    )
    plan = build_system_prompt(
        mode=AppMode.PLAN,
        workspace=Path("/tmp/workspace"),
        project_context_enabled=False,
    )

    assert "You are DeepSeek TUI" in agent
    assert "You are DeepSeek TUI" in plan
    assert len(plan) < len(agent)


def test_subagent_mandate_block_appended_when_requested() -> None:
    from deepseek_tui.engine.subagent_intent import SUBAGENT_MANDATE_BLOCK

    base = build_system_prompt(
        mode=AppMode.AGENT,
        workspace=Path("/tmp/workspace"),
        project_context_enabled=False,
        subagent_mandate=False,
    )
    mandated = build_system_prompt(
        mode=AppMode.AGENT,
        workspace=Path("/tmp/workspace"),
        project_context_enabled=False,
        subagent_mandate=True,
    )

    assert SUBAGENT_MANDATE_BLOCK.strip() in mandated
    assert len(mandated) > len(base)
