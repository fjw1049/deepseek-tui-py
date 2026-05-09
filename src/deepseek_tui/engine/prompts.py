"""Engine-level system prompt builder.

Mirrors `crates/tui/src/prompts.rs::system_prompt_for_mode_with_context`.
"""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.prompts import (
    COMPACT_TEMPLATE,
    AppMode,
    Personality,
    compose_prompt,
)

HANDOFF_RELATIVE_PATH = ".deepseek/handoff.md"
INSTRUCTIONS_FILE_MAX_BYTES = 100 * 1024


def build_system_prompt(
    override: str | None = None,
    *,
    mode: AppMode = AppMode.AGENT,
    personality: Personality = Personality.CALM,
    workspace: Path | None = None,
    working_set_summary: str | None = None,
    skills_context: str | None = None,
) -> str:
    """Build the full system prompt for the engine.

    If *override* is provided and non-empty, it is used verbatim (for tests
    and AppRuntime callers that supply their own prompt).

    Otherwise, composes from layered templates following the Rust ordering:
      1. mode prompt (base + personality + mode + approval)
      2. context management guidance (Agent/Yolo only)
      3. skills context (available skills list)
      4. compaction handoff template
      5. previous-session handoff (volatile)
      6. working-set summary (volatile)
    """
    if override is not None and override.strip():
        return override

    full_prompt = compose_prompt(mode, personality)

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

    # Compaction handoff template
    full_prompt += "\n\n" + COMPACT_TEMPLATE()

    # ── Volatile-content boundary ──
    # Previous-session handoff
    if workspace is not None:
        handoff_block = _load_handoff_block(workspace)
        if handoff_block:
            full_prompt += "\n\n" + handoff_block

    # Working-set summary
    if working_set_summary and working_set_summary.strip():
        full_prompt += "\n\n" + working_set_summary

    return full_prompt


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
