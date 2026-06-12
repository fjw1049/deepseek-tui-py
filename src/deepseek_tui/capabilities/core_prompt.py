"""Core prompt contributions owned by the built-in host."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

from deepseek_tui.host.prompts import (
    FunctionPromptContributor,
    PromptContributor,
    PromptContributorContext,
)
from deepseek_tui.prompts import COMPACT_TEMPLATE, AppMode

HANDOFF_RELATIVE_PATH = ".deepseek/handoff.md"


def core_prompt_contributors() -> list[PromptContributor]:
    return [
        FunctionPromptContributor(
            "project-context",
            100,
            _project_context_contribution,
        ),
        FunctionPromptContributor(
            "environment",
            200,
            _environment_contribution,
        ),
        FunctionPromptContributor("context-management", 500, _context_management),
        FunctionPromptContributor("compaction-template", 800, lambda _ctx: COMPACT_TEMPLATE()),
        FunctionPromptContributor("handoff", 900, _handoff_contribution),
        FunctionPromptContributor("working-set", 1300, _working_set),
        FunctionPromptContributor("subagent-mandate", 1400, _subagent_mandate),
    ]


def render_environment_block(
    workspace: Path,
    locale_tag: str = "en",
) -> str:
    shell = os.environ.get("SHELL", "unknown")
    pwd = workspace.expanduser().resolve()
    return (
        "## Environment\n"
        "\n"
        f"- lang: {locale_tag}\n"
        f"- deepseek_version: {_deepseek_version()}\n"
        f"- platform: {sys.platform}\n"
        f"- shell: {shell}\n"
        f"- pwd: {pwd}"
    )


def _deepseek_version() -> str:
    try:
        from importlib.metadata import version as _v

        return _v("deepseek-tui")
    except Exception:  # noqa: BLE001
        return "unknown"


def _project_context_contribution(ctx: PromptContributorContext) -> str | None:
    if ctx.workspace is None or not ctx.project_context_enabled:
        return None
    from deepseek_tui.engine.project_context import load_project_context_with_parents

    block = load_project_context_with_parents(ctx.workspace).as_system_block()
    return block or None


def _environment_contribution(ctx: PromptContributorContext) -> str | None:
    if ctx.workspace is None:
        return None
    return render_environment_block(ctx.workspace, ctx.locale_tag)


def _context_management(ctx: PromptContributorContext) -> str | None:
    if ctx.mode not in (AppMode.AGENT, AppMode.YOLO, AppMode.GOAL, AppMode.WORKFLOW):
        return None
    return (
        "## Context Management\n\n"
        "When the conversation gets long (you'll see a context usage indicator), you can:\n"
        "1. Use `/compact` to summarize earlier context and free up space\n"
        "2. The system will preserve important information "
        "(files you're working on, recent messages, tool results)\n"
        "3. After compaction, you'll see a summary of what was discussed "
        "and can continue seamlessly\n\n"
        "If you notice context is getting long (>80%), "
        "proactively suggest using `/compact` to the user."
    )


def _handoff_contribution(ctx: PromptContributorContext) -> str | None:
    if ctx.workspace is None:
        return None
    return _load_handoff_block(ctx.workspace)


def _load_handoff_block(workspace: Path) -> str | None:
    path = workspace / HANDOFF_RELATIVE_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    return (
        f"## Previous Session Handoff\n\n"
        f"The previous session in this workspace left a handoff at "
        f"`{HANDOFF_RELATIVE_PATH}`. Consider it the first artifact to read "
        f"on this turn — open blockers, in-flight changes, and recent decisions "
        f"live there. Update or rewrite it before exiting if state changes "
        f"materially.\n\n{trimmed}"
    )


def _working_set(ctx: PromptContributorContext) -> str | None:
    if ctx.working_set_summary and ctx.working_set_summary.strip():
        return ctx.working_set_summary
    return None


def _subagent_mandate(ctx: PromptContributorContext) -> str | None:
    if not ctx.subagent_mandate:
        return None
    from deepseek_tui.engine.subagent_intent import SUBAGENT_MANDATE_BLOCK

    return cast(str, SUBAGENT_MANDATE_BLOCK)
