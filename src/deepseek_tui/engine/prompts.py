"""Prompt composition and tool profiles.

Consolidates engine/prompts.py, tool_profiles.py, and prompts/ package.
"""

from __future__ import annotations



# ======================================================================
# From engine/prompts.py
# ======================================================================

"""Engine-level system prompt builder.

Mirrors `crates/tui/src/prompts.rs::system_prompt_for_mode_with_context`.
"""


import os
import sys
from pathlib import Path

from deepseek_tui.memory.coordinator import wrap_relevant_memories_system_block
from deepseek_tui.memory.coordinator import RecallResult

import enum

HANDOFF_RELATIVE_PATH = ".deepseek/handoff.md"
INSTRUCTIONS_FILE_MAX_BYTES = 100 * 1024


class Personality(enum.Enum):
    """Personality overlay selection."""
    CALM = "calm"
    PLAYFUL = "playful"

    def prompt(self) -> str:
        if self is Personality.CALM:
            return CALM_PERSONALITY()
        return PLAYFUL_PERSONALITY()

    @staticmethod
    def from_settings(calm_mode: bool) -> Personality:
        return Personality.CALM if calm_mode else Personality.CALM


class AppMode(enum.Enum):
    """Application mode."""
    AGENT = "agent"
    YOLO = "yolo"
    PLAN = "plan"
    WORKFLOW = "workflow"

    def mode_prompt(self) -> str:
        if self is AppMode.AGENT:
            return AGENT_MODE()
        elif self is AppMode.YOLO:
            return YOLO_MODE()
        elif self is AppMode.WORKFLOW:
            return WORKFLOW_MODE()
        return PLAN_MODE()

    def approval_prompt(self) -> str:
        if self is AppMode.YOLO:
            return AUTO_APPROVAL()
        elif self is AppMode.PLAN:
            return NEVER_APPROVAL()
        return SUGGEST_APPROVAL()


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
        from deepseek_tui.engine.context import (
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


    if memory_recall and memory_recall.append_system.strip():
        full_prompt += "\n\n" + memory_recall.append_system.strip()

    # Context Management (Agent / Yolo only)
    if mode in (AppMode.AGENT, AppMode.YOLO, AppMode.WORKFLOW):
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
        from deepseek_tui.workflow.adapters import workflow_guidelines_snippet

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
    from deepseek_tui.memory.coordinator import compose_block

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


# ======================================================================
# From engine/tool_profiles.py
# ======================================================================

"""Tool visibility profiles — slim catalogs for automation composer and cron runs."""


from typing import Any

AUTOMATION_COMPOSER_HEADING = "[Scheduled automation request]"
CRON_PROMPT_PREFIX = "[cron:"

TOOL_PROFILE_FULL = "full"
TOOL_PROFILE_AUTOMATION_COMPOSER = "automation_composer"
TOOL_PROFILE_CRON = "cron"

# Composer: schedule creation only — no MCP, no tool_search, no shell.
_AUTOMATION_COMPOSER_NATIVE = frozenset(
    {
        "current_time",
        "automation_create",
        "automation_list",
        "automation_read",
        "automation_update",
        "automation_pause",
        "automation_resume",
        "automation_delete",
        "automation_run",
    }
)

# Cron execution: search/fetch + selected MCP families; no automation_* churn.
_CRON_NATIVE = frozenset(
    {
        "web_search",
        "fetch_url",
        "read_file",
        "grep_files",
    }
)

_CRON_MCP_PREFIXES = (
    "mcp_bing",
    "mcp_china",
    "mcp_yahoo",
    "mcp_fetch",
    "mcp_pozansky",
)


def detect_tool_profile_from_prompt(prompt: str) -> str:
    """Infer profile from wrapped user / cron prompt text."""
    text = prompt.lstrip()
    if text.startswith(AUTOMATION_COMPOSER_HEADING):
        return TOOL_PROFILE_AUTOMATION_COMPOSER
    if text.startswith(CRON_PROMPT_PREFIX):
        return TOOL_PROFILE_CRON
    return TOOL_PROFILE_FULL


def profile_includes_tool_search(profile: str | None) -> bool:
    return profile in (None, TOOL_PROFILE_FULL)


def _tool_name(entry: dict[str, Any]) -> str:
    fn = entry.get("function", entry)
    return str(fn.get("name", ""))


def filter_tools_for_profile(
    tools: list[dict[str, Any]], profile: str | None
) -> list[dict[str, Any]]:
    """Return a subset of API tool descriptors for the given profile."""
    if not profile or profile == TOOL_PROFILE_FULL:
        return tools

    if profile == TOOL_PROFILE_AUTOMATION_COMPOSER:
        allowed_native = _AUTOMATION_COMPOSER_NATIVE
        out: list[dict[str, Any]] = []
        for entry in tools:
            name = _tool_name(entry)
            if name in allowed_native:
                clone = _copy_tool_entry(entry)
                fn = clone.get("function", clone)
                fn["defer_loading"] = False
                out.append(clone)
        return out

    if profile == TOOL_PROFILE_CRON:
        out = []
        for entry in tools:
            name = _tool_name(entry)
            if name in _CRON_NATIVE or any(
                name.startswith(prefix) for prefix in _CRON_MCP_PREFIXES
            ):
                clone = _copy_tool_entry(entry)
                fn = clone.get("function", clone)
                fn["defer_loading"] = False
                out.append(clone)
        return out

    return tools


def _copy_tool_entry(entry: dict[str, Any]) -> dict[str, Any]:
    fn = entry.get("function", entry)
    if not isinstance(fn, dict):
        return dict(entry)
    return {
        "type": entry.get("type", "function"),
        "function": dict(fn),
    }


# ======================================================================
# From prompts/__init__.py
# ======================================================================

"""System prompt composition from layered template files.

Mirrors `crates/tui/src/prompts.rs` — composable layers loaded at runtime:
  base.md → personality overlay → mode delta → approval policy

Prompt files are copied verbatim from the Rust source (English, unmodified).
"""


import enum
from importlib.resources import files as pkg_files

_PACKAGE = "deepseek_tui.prompts"


def _load(relative: str) -> str:
    """Load a prompt file from the package data directory."""
    return (pkg_files(_PACKAGE) / relative).read_text(encoding="utf-8")


# Lazy-loaded prompt constants (mirrors Rust include_str! constants)
_cache: dict[str, str] = {}


def _get(key: str) -> str:
    if key not in _cache:
        _cache[key] = _load(key)
    return _cache[key]


def BASE_PROMPT() -> str:  # noqa: N802
    return _get("base.md")


def CALM_PERSONALITY() -> str:  # noqa: N802
    return _get("personalities/calm.md")


def PLAYFUL_PERSONALITY() -> str:  # noqa: N802
    return _get("personalities/playful.md")


def AGENT_MODE() -> str:  # noqa: N802
    return _get("modes/agent.md")


def PLAN_MODE() -> str:  # noqa: N802
    return _get("modes/plan.md")


def YOLO_MODE() -> str:  # noqa: N802
    return _get("modes/yolo.md")


def WORKFLOW_MODE() -> str:  # noqa: N802
    return _get("modes/workflow.md")


def AUTO_APPROVAL() -> str:  # noqa: N802
    return _get("approvals/auto.md")


def SUGGEST_APPROVAL() -> str:  # noqa: N802
    return _get("approvals/suggest.md")


def NEVER_APPROVAL() -> str:  # noqa: N802
    return _get("approvals/never.md")


def COMPACT_TEMPLATE() -> str:  # noqa: N802
    return _get("compact.md")


def CYCLE_HANDOFF() -> str:  # noqa: N802
    return _get("cycle_handoff.md")


def SUBAGENT_OUTPUT_FORMAT() -> str:  # noqa: N802
    return _get("subagent_output_format.md")


# (Personality and AppMode moved to top of file)


# ── Composition ──────────────────────────────────────────────────────────


def compose_prompt(mode: AppMode, personality: Personality = Personality.CALM) -> str:
    """Compose the full system prompt in deterministic order.

    Order (most-static to most-volatile for KV prefix cache):
      1. base.md        — core identity, toolbox, execution contract
      2. personality    — voice and tone overlay
      3. mode delta     — mode-specific permissions and workflow
      4. approval policy — tool-approval behavior
    """
    parts = [
        BASE_PROMPT().strip(),
        personality.prompt().strip(),
        mode.mode_prompt().strip(),
        mode.approval_prompt().strip(),
    ]
    return "\n\n".join(parts)


def load_prompt(name: str) -> str:
    """Load a prompt by name (for backward compatibility).

    Maps prompt names to their corresponding loader functions.
    Used by SubAgentType.system_prompt() to load subagent_output_format.
    """
    name_lower = name.lower().replace("-", "_")
    loaders = {
        "subagent_output_format": SUBAGENT_OUTPUT_FORMAT,
        "base": BASE_PROMPT,
        "calm_personality": CALM_PERSONALITY,
        "playful_personality": PLAYFUL_PERSONALITY,
        "agent_mode": AGENT_MODE,
        "plan_mode": PLAN_MODE,
        "yolo_mode": YOLO_MODE,
        "workflow_mode": WORKFLOW_MODE,
        "auto_approval": AUTO_APPROVAL,
        "suggest_approval": SUGGEST_APPROVAL,
        "never_approval": NEVER_APPROVAL,
        "compact_template": COMPACT_TEMPLATE,
        "cycle_handoff": CYCLE_HANDOFF,
    }
    loader = loaders.get(name_lower)
    if loader is None:
        raise ValueError(f"Unknown prompt name: {name}")
    return loader()
