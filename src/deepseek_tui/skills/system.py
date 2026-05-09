"""Bundled system skills.

Mirrors ``crates/tui/src/skills/system.rs``. Installs the bundled
``skill-creator`` skill at startup if not already present.
"""
from __future__ import annotations

import logging
from pathlib import Path

from deepseek_tui.skills import (
    SKILL_FILENAME,
    SYSTEM_VERSION_MARKER,
    default_skills_dir,
)

__all__ = ["install_system_skills", "uninstall_system_skills"]

_LOG = logging.getLogger(__name__)

SYSTEM_SKILL_VERSION = "0.1.0"

SKILL_CREATOR_BODY = """\
---
name: skill-creator
description: Help create new SKILL.md definitions for custom skills.
---

# Skill Creator

You are a skill-creation assistant. Help the user write a new SKILL.md
file that follows the standard format:

1. **Frontmatter** (YAML between `---` delimiters):
   - `name`: short kebab-case identifier
   - `description`: one-line summary of what the skill does

2. **Body**: Markdown instructions that will be injected into the
   system prompt when the skill is activated.

## Guidelines

- Keep instructions concise and actionable.
- Use bullet points for step-by-step workflows.
- Include examples where helpful.
- Avoid duplicating capabilities already in the base system prompt.
"""


def install_system_skills(skills_dir: Path | None = None) -> None:
    """Install bundled system skills if not already present.

    Called at TUI startup. Mirrors Rust ``install_system_skills``.
    """
    target = skills_dir or default_skills_dir()
    target.mkdir(parents=True, exist_ok=True)

    _install_skill_creator(target)


def _install_skill_creator(skills_dir: Path) -> None:
    """Install the skill-creator skill."""
    dest = skills_dir / "skill-creator"
    version_marker = dest / SYSTEM_VERSION_MARKER

    if version_marker.is_file():
        existing_version = version_marker.read_text(encoding="utf-8").strip()
        if existing_version == SYSTEM_SKILL_VERSION:
            return

    dest.mkdir(parents=True, exist_ok=True)
    (dest / SKILL_FILENAME).write_text(SKILL_CREATOR_BODY, encoding="utf-8")
    version_marker.write_text(SYSTEM_SKILL_VERSION, encoding="utf-8")
    _LOG.info("Installed system skill: skill-creator v%s", SYSTEM_SKILL_VERSION)


def uninstall_system_skills(skills_dir: Path | None = None) -> None:
    """Remove bundled system skills.

    Used by tests and ``deepseek setup --clean``.
    """
    import shutil

    target = skills_dir or default_skills_dir()
    dest = target / "skill-creator"
    if dest.is_dir():
        shutil.rmtree(dest)
        _LOG.info("Uninstalled system skill: skill-creator")
