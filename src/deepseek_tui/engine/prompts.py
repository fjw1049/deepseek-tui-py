"""Engine-level system prompt builder.

Mirrors `crates/tui/src/prompts.rs::system_prompt_for_mode_with_context`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from deepseek_tui.memory.formatting import wrap_relevant_memories_system_block
from deepseek_tui.memory.provider import RecallResult
from deepseek_tui.prompts import (
    COMPACT_TEMPLATE,
    AppMode,
    Personality,
    compose_prompt,
)

HANDOFF_RELATIVE_PATH = ".deepseek/handoff.md"
INSTRUCTIONS_FILE_MAX_BYTES = 100 * 1024


def _deepseek_version() -> str:
    """Resolve the installed package version (best-effort)."""
    try:
        from importlib.metadata import version as _v

        return _v("deepseek-tui")
    except Exception:  # noqa: BLE001 — best-effort, no propagating ImportError
        return "unknown"


def render_environment_block(
    workspace: Path,
    locale_tag: str = "en",
) -> str:
    """Render the ``## Environment`` block.

    Mirrors Rust ``render_environment_block`` (prompts.rs:51-66). Lists:
    locale, runtime version, host platform, login shell, current working
    directory. All values are session-stable so the block sits in the
    workspace-static prefix and benefits from KV prefix cache hits.

    The block anchors the LLM in *where it is* — without it, models
    hallucinate ``/home/user/...`` paths from the training distribution
    instead of using the actual ``pwd``.
    """
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


def build_system_prompt(
    override: str | None = None,
    *,
    mode: AppMode = AppMode.AGENT,
    personality: Personality = Personality.CALM,
    workspace: Path | None = None,
    working_set_summary: str | None = None,
    skills_context: str | None = None,
    locale_tag: str = "en",
    project_context_enabled: bool = True,
    subagent_mandate: bool = False,
    memory_enabled: bool = False,
    memory_path: Path | None = None,
    memory_recall: RecallResult | None = None,
    curated_snapshot: str | None = None,
    session_evolution_lines: list[str] | None = None,
    evolution_enabled: bool = False,
    workflow_guidelines: bool = False,
) -> str:
    """Build the full system prompt for the engine.

    If *override* is provided and non-empty, it is used verbatim (for tests
    and AppRuntime callers that supply their own prompt).

    Otherwise, composes from layered templates following the Rust ordering:
      1. mode prompt (base + personality + mode + approval)
      2. project_context block (AGENTS.md / CLAUDE.md / instructions.md)
      3. ## Environment block (lang / version / platform / shell / pwd)
      4. context management guidance (Agent/Yolo only)
      5. skills context (available skills list)
      6. compaction handoff template
      7. previous-session handoff (volatile)
      8. working-set summary (volatile)

    Setting ``project_context_enabled=False`` skips the project_context
    block — used by tests that don't want disk I/O. The auto-generate
    side effect is suppressed in that case.
    """
    if override is not None and override.strip():
        return override

    full_prompt = compose_prompt(mode, personality)

    # Project instructions (AGENTS.md / CLAUDE.md / .deepseek/instructions.md
    # / parent dirs / ~/.deepseek/AGENTS.md / auto-gen). Goes above the
    # Environment block so it stays in the workspace-static prefix layer.
    if workspace is not None and project_context_enabled:
        from deepseek_tui.engine.project_context import (
            load_project_context_with_parents,
        )

        project_ctx = load_project_context_with_parents(workspace)
        block = project_ctx.as_system_block()
        if block:
            full_prompt += "\n\n" + block

    # ## Environment — session-stable. Insert above all per-turn content
    # so it lives in the KV prefix cache layer.
    if workspace is not None:
        full_prompt += "\n\n" + render_environment_block(workspace, locale_tag)

    if evolution_enabled and curated_snapshot:
        full_prompt += "\n\n" + curated_snapshot
    if evolution_enabled:
        from deepseek_tui.evolution.prompts import (
            EVOLUTION_GUIDANCE,
            SKILLS_EVOLUTION_GUIDANCE,
        )

        full_prompt += "\n\n" + EVOLUTION_GUIDANCE
        full_prompt += "\n\n" + SKILLS_EVOLUTION_GUIDANCE

    if memory_recall and memory_recall.append_system.strip():
        full_prompt += "\n\n" + memory_recall.append_system.strip()

    # Context Management (Agent / Yolo only)
    if mode in (AppMode.AGENT, AppMode.YOLO):
        full_prompt += (
            "\n\n## Context Management\n\n"
            "When the conversation gets long (you'll see a context usage indicator), you can:\n"
            "1. Use `/compact` to summarize earlier context and free up space\n"
            "2. The system will preserve important information "
            "(files you're working on, recent messages, tool results)\n"
            "3. After compaction, you'll see a summary of what was discussed "
            "and can continue seamlessly\n\n"
            "If you notice context is getting long (>80%), "
            "proactively suggest using `/compact` to the user."
        )

    # Skills context (mirrors Rust skills injection into system prompt)
    if skills_context and skills_context.strip():
        full_prompt += "\n\n" + skills_context

    if workflow_guidelines:
        from deepseek_tui.workflow.prompts import workflow_guidelines_snippet

        snippet = workflow_guidelines_snippet()
        if snippet:
            full_prompt += "\n\n" + snippet

    # Compaction handoff template
    full_prompt += "\n\n" + COMPACT_TEMPLATE()

    # ── Volatile-content boundary ──
    # Previous-session handoff
    if workspace is not None:
        handoff_block = _load_handoff_block(workspace)
        if handoff_block:
            full_prompt += "\n\n" + handoff_block

    if (
        memory_recall
        and memory_recall.l1_context.strip()
        and memory_recall.inject_position == "system_volatile"
    ):
        volatile_l1 = wrap_relevant_memories_system_block(memory_recall.l1_context)
        if volatile_l1:
            full_prompt += "\n\n" + volatile_l1

    if session_evolution_lines:
        full_prompt += "\n\n<session-evolution>\n"
        full_prompt += "\n".join(session_evolution_lines)
        full_prompt += "\n</session-evolution>"

    # User memory (~/.deepseek/memory.md) — opt-in, re-read each turn.
    memory_block = _load_user_memory(memory_enabled, memory_path)
    if memory_block:
        full_prompt += "\n\n" + memory_block

    # Working-set summary
    if working_set_summary and working_set_summary.strip():
        full_prompt += "\n\n" + working_set_summary

    if subagent_mandate:
        from deepseek_tui.engine.subagent_intent import SUBAGENT_MANDATE_BLOCK

        full_prompt += "\n\n" + SUBAGENT_MANDATE_BLOCK

    return full_prompt


def _load_user_memory(
    enabled: bool,
    memory_path: Path | None,
) -> str | None:
    """Compose ``<user_memory>`` block — mirrors ``memory::compose_block``."""
    if memory_path is None:
        from deepseek_tui.config.paths import user_memory_path

        memory_path = user_memory_path()
    from deepseek_tui.memory.user_memory import compose_block

    return compose_block(enabled, memory_path)


def _load_handoff_block(workspace: Path) -> str | None:
    """Read workspace-local handoff artifact if present."""
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
