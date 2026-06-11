from __future__ import annotations

from pathlib import Path

from deepseek_tui.capabilities.core_prompt import core_prompt_contributors
from deepseek_tui.capabilities.evolution import evolution_prompt_contributors
from deepseek_tui.capabilities.memory import memory_prompt_contributors
from deepseek_tui.capabilities.skills import skills_prompt_contributors
from deepseek_tui.capabilities.workflow import workflow_prompt_contributors
from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.host.prompts import (
    FunctionPromptContributor,
    PromptContributorContext,
    append_prompt_contributions,
)
from deepseek_tui.memory.provider import RecallResult
from deepseek_tui.prompts import AppMode


def test_prompt_contributors_are_applied_by_order(tmp_path: Path) -> None:
    context = PromptContributorContext(mode=AppMode.AGENT, workspace=tmp_path)

    prompt = append_prompt_contributions(
        "base",
        context,
        [
            FunctionPromptContributor("second", 200, lambda _ctx: "second"),
            FunctionPromptContributor("first", 100, lambda _ctx: "first"),
            FunctionPromptContributor("empty", 150, lambda _ctx: ""),
        ],
    )

    assert prompt == "base\n\nfirst\n\nsecond"


def test_core_prompt_contributors_include_static_and_volatile_blocks(
    tmp_path: Path,
) -> None:
    handoff_dir = tmp_path / ".deepseek"
    handoff_dir.mkdir()
    (handoff_dir / "handoff.md").write_text("handoff marker", encoding="utf-8")
    context = PromptContributorContext(
        mode=AppMode.AGENT,
        workspace=tmp_path,
        project_context_enabled=False,
        working_set_summary="working set marker",
    )

    rendered = "\n\n".join(
        contribution.text
        for contributor in core_prompt_contributors()
        if (contribution := contributor.contribute(context)) is not None
    )

    assert "## Environment" in rendered
    assert "## Context Management" in rendered
    assert "## Compaction Handoff" in rendered
    assert "## Previous Session Handoff" in rendered
    assert "handoff marker" in rendered
    assert "working set marker" in rendered


def test_default_system_prompt_contributor_order_is_preserved(
    tmp_path: Path,
) -> None:
    handoff_dir = tmp_path / ".deepseek"
    handoff_dir.mkdir()
    (handoff_dir / "handoff.md").write_text("handoff marker", encoding="utf-8")
    recall = RecallResult(
        append_system="<persona>\nstable memory marker\n</persona>",
        l1_context="- volatile memory marker",
        inject_position="system_volatile",
    )

    prompt = build_system_prompt(
        None,
        mode=AppMode.AGENT,
        workspace=tmp_path,
        project_context_enabled=False,
        skills_context="skills marker",
        working_set_summary="working set marker",
        memory_recall=recall,
        curated_snapshot="curated snapshot marker",
        session_evolution_lines=["session evolution marker"],
        evolution_enabled=True,
        workflow_guidelines=True,
    )

    markers = [
        "## Environment",
        "curated snapshot marker",
        "## Curated Memory",
        "stable memory marker",
        "## Context Management",
        "skills marker",
        "## Workflow tool",
        "## Compaction Handoff",
        "## Previous Session Handoff",
        "volatile memory marker",
        "<session-evolution>",
        "working set marker",
    ]
    positions = [prompt.index(marker) for marker in markers]

    assert positions == sorted(positions)


def test_skills_prompt_contributor_uses_rendered_context(tmp_path: Path) -> None:
    context = PromptContributorContext(
        mode=AppMode.AGENT,
        workspace=tmp_path,
        skills_context="skills marker",
    )

    contribution = skills_prompt_contributors()[0].contribute(context)

    assert contribution is not None
    assert contribution.text == "skills marker"


def test_workflow_prompt_contributor_respects_feature_flag(tmp_path: Path) -> None:
    disabled = PromptContributorContext(
        mode=AppMode.AGENT,
        workspace=tmp_path,
        workflow_guidelines=False,
    )
    enabled = PromptContributorContext(
        mode=AppMode.AGENT,
        workspace=tmp_path,
        workflow_guidelines=True,
    )

    contributor = workflow_prompt_contributors()[0]

    assert contributor.contribute(disabled) is None
    contribution = contributor.contribute(enabled)
    assert contribution is not None
    assert "## Workflow tool" in contribution.text


def test_memory_prompt_contributors_preserve_recall_blocks(tmp_path: Path) -> None:
    context = PromptContributorContext(
        mode=AppMode.AGENT,
        workspace=tmp_path,
        memory_recall=RecallResult(
            append_system="<persona>\nstable memory marker\n</persona>",
            l1_context="- volatile memory marker",
            inject_position="system_volatile",
        ),
        memory_enabled=False,
        memory_path=tmp_path / "memory.md",
    )
    contributions = [
        contribution
        for contributor in memory_prompt_contributors()
        if (contribution := contributor.contribute(context)) is not None
    ]

    rendered = "\n\n".join(contribution.text for contribution in contributions)

    assert "stable memory marker" in rendered
    assert "<relevant-memories>" in rendered
    assert "volatile memory marker" in rendered


def test_evolution_prompt_contributors_respect_feature_flag(tmp_path: Path) -> None:
    disabled = PromptContributorContext(
        mode=AppMode.AGENT,
        workspace=tmp_path,
        curated_snapshot="curated snapshot marker",
        session_evolution_lines=["session evolution marker"],
        evolution_enabled=False,
    )
    enabled = PromptContributorContext(
        mode=AppMode.AGENT,
        workspace=tmp_path,
        curated_snapshot="curated snapshot marker",
        session_evolution_lines=["session evolution marker"],
        evolution_enabled=True,
    )

    disabled_text = [
        contribution.text
        for contributor in evolution_prompt_contributors()
        if (contribution := contributor.contribute(disabled)) is not None
    ]
    enabled_text = "\n\n".join(
        contribution.text
        for contributor in evolution_prompt_contributors()
        if (contribution := contributor.contribute(enabled)) is not None
    )

    assert disabled_text == ["<session-evolution>\nsession evolution marker\n</session-evolution>"]
    assert "curated snapshot marker" in enabled_text
    assert "## Curated Memory" in enabled_text
    assert "session evolution marker" in enabled_text
