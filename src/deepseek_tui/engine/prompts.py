"""Engine-level system prompt builder.

Mirrors `crates/tui/src/prompts.rs::system_prompt_for_mode_with_context`.
"""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.capabilities.core_prompt import (
    render_environment_block as _render_environment_block,
)
from deepseek_tui.host.prompts import (
    PromptContributorContext,
    append_prompt_contributions,
)
from deepseek_tui.memory.provider import RecallResult
from deepseek_tui.prompts import AppMode, Personality, compose_prompt

INSTRUCTIONS_FILE_MAX_BYTES = 100 * 1024


def render_environment_block(
    workspace: Path,
    locale_tag: str = "en",
) -> str:
    return _render_environment_block(workspace, locale_tag)


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

    context = PromptContributorContext(
        mode=mode,
        workspace=workspace,
        working_set_summary=working_set_summary,
        skills_context=skills_context,
        locale_tag=locale_tag,
        project_context_enabled=project_context_enabled,
        subagent_mandate=subagent_mandate,
        memory_enabled=memory_enabled,
        memory_path=memory_path,
        memory_recall=memory_recall,
        curated_snapshot=curated_snapshot,
        session_evolution_lines=session_evolution_lines,
        evolution_enabled=evolution_enabled,
        workflow_guidelines=workflow_guidelines,
    )
    from deepseek_tui.host.assembler import resolve_assembly_prompt_contributors

    return append_prompt_contributions(
        compose_prompt(mode, personality),
        context,
        resolve_assembly_prompt_contributors(),
    )
