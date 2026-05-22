"""System prompt composition from layered template files.

Mirrors `crates/tui/src/prompts.rs` — composable layers loaded at runtime:
  base.md → personality overlay → mode delta → approval policy

Prompt files are copied verbatim from the Rust source (English, unmodified).
"""

from __future__ import annotations

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


# ── Enums ────────────────────────────────────────────────────────────────


class Personality(enum.Enum):
    """Personality overlay selection (mirrors Rust Personality enum)."""
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
    """Application mode (mirrors Rust AppMode enum)."""
    AGENT = "agent"
    YOLO = "yolo"
    PLAN = "plan"

    def mode_prompt(self) -> str:
        if self is AppMode.AGENT:
            return AGENT_MODE()
        elif self is AppMode.YOLO:
            return YOLO_MODE()
        return PLAN_MODE()

    def approval_prompt(self) -> str:
        if self is AppMode.AGENT:
            return SUGGEST_APPROVAL()
        elif self is AppMode.YOLO:
            return AUTO_APPROVAL()
        return NEVER_APPROVAL()


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
