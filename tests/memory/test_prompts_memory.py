from pathlib import Path

from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.memory.coordinator import RecallResult
from deepseek_tui.prompts import AppMode


def test_build_system_prompt_injects_stable_and_user_recall(tmp_path: Path) -> None:
    recall = RecallResult(
        l1_context="- (persona) likes tea",
        append_system="<persona>\nCalm helper\n</persona>",
        inject_position="user",
    )
    prompt = build_system_prompt(
        None,
        workspace=tmp_path,
        mode=AppMode.AGENT,
        project_context_enabled=False,
        memory_recall=recall,
    )
    assert "<persona>" in prompt
    assert "Calm helper" in prompt
    assert "<relevant-memories>" not in prompt


def test_build_system_prompt_system_volatile_l1(tmp_path: Path) -> None:
    recall = RecallResult(
        l1_context="- (episodic) shipped v2",
        append_system="",
        inject_position="system_volatile",
    )
    prompt = build_system_prompt(
        None,
        workspace=tmp_path,
        mode=AppMode.AGENT,
        project_context_enabled=False,
        memory_recall=recall,
    )
    assert "<relevant-memories>" in prompt
    assert "shipped v2" in prompt
    assert prompt.count("<relevant-memories>") == 1
    assert prompt.count("</relevant-memories>") == 1
