"""Skills subsystem — discovery, install, and activation.

Mirrors ``crates/tui/src/skills/mod.rs``. A skill is a directory
containing ``SKILL.md`` with YAML frontmatter (name, description)
followed by the skill body. Skills are discovered by scanning
subdirectories of the configured skills directory.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Skill",
    "SkillRegistry",
    "default_skills_dir",
    "discover_in_workspace",
    "render_available_skills_context",
]

_LOG = logging.getLogger(__name__)

SKILL_FILENAME = "SKILL.md"
INSTALLED_FROM_MARKER = ".installed-from"
TRUSTED_MARKER = ".trusted"
SYSTEM_VERSION_MARKER = ".system-installed-version"


def default_skills_dir() -> Path:
    """Return ``./.deepseek/skills``.

    Project-local since 2026-05-11: skills travel with the checkout.
    """
    from deepseek_tui.config.paths import dot_deepseek_dir

    return dot_deepseek_dir() / "skills"


@dataclass(frozen=True, slots=True)
class Skill:
    """Parsed representation of a SKILL.md definition.

    Mirrors Rust ``Skill`` (skills/mod.rs:41-51).
    """

    name: str
    description: str
    body: str
    path: Path


@dataclass(slots=True)
class SkillRegistry:
    """Collection of discovered skills.

    Mirrors Rust ``SkillRegistry`` — a ``Vec<Skill>`` plus warnings.
    """

    skills: list[Skill] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def discover(cls, skills_dir: Path) -> SkillRegistry:
        """Scan ``skills_dir`` for subdirectories containing SKILL.md.

        Mirrors Rust ``SkillRegistry::discover`` (mod.rs:95-140).
        """
        registry = cls()
        if not skills_dir.is_dir():
            return registry
        for child in sorted(skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / SKILL_FILENAME
            if not skill_file.is_file():
                continue
            try:
                skill = _parse_skill_file(skill_file)
                registry.skills.append(skill)
            except Exception as exc:
                warning = f"Failed to parse {skill_file}: {exc}"
                _LOG.warning(warning)
                registry.warnings.append(warning)
        return registry

    def get(self, name: str) -> Skill | None:
        """Look up a skill by name (case-insensitive)."""
        name_lower = name.lower()
        for skill in self.skills:
            if skill.name.lower() == name_lower:
                return skill
        return None

    def list_names(self) -> list[str]:
        return [s.name for s in self.skills]

    @property
    def is_empty(self) -> bool:
        return len(self.skills) == 0

    def __len__(self) -> int:
        return len(self.skills)


# ── Frontmatter parsing ──────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)


def _parse_skill_file(path: Path) -> Skill:
    """Parse a SKILL.md file into a Skill instance.

    Mirrors Rust frontmatter parsing (mod.rs:200-270).
    """
    content = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = content

    match = _FRONTMATTER_RE.match(content)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip().lower()] = value.strip()
        body = content[match.end():]

    name = meta.get("name", path.parent.name)
    description = meta.get("description", "")

    return Skill(
        name=name,
        description=description,
        body=body.strip(),
        path=path,
    )


# ── Workspace discovery ──────────────────────────────────────────────────


def skills_directories(
    skills_dir: Path | None = None,
    workspace: Path | None = None,
) -> list[Path]:
    """Return ordered list of skill directories to scan.

    Mirrors Rust ``skills_directories`` (mod.rs:60-80).
    """
    dirs: list[Path] = []
    primary = skills_dir or default_skills_dir()
    if primary.is_dir():
        dirs.append(primary)
    if workspace:
        local = workspace / ".deepseek" / "skills"
        if local.is_dir() and local != primary:
            dirs.append(local)
    return dirs


def discover_in_workspace(
    skills_dir: Path | None = None,
    workspace: Path | None = None,
) -> SkillRegistry:
    """Discover skills across all skill directories.

    First directory wins on name collisions (mirrors Rust
    ``discover_in_workspace``).
    """
    merged = SkillRegistry()
    seen_names: set[str] = set()
    for d in skills_directories(skills_dir, workspace):
        reg = SkillRegistry.discover(d)
        for skill in reg.skills:
            if skill.name.lower() not in seen_names:
                merged.skills.append(skill)
                seen_names.add(skill.name.lower())
        merged.warnings.extend(reg.warnings)
    return merged


# ── Prompt context rendering ─────────────────────────────────────────────


def render_available_skills_context(
    registry: SkillRegistry,
) -> str:
    """Render the progressive-disclosure skills block for the system prompt.

    Lists name + description only (body loaded on demand via load_skill).
    Mirrors Rust ``render_available_skills_context`` (mod.rs:300-330).
    """
    if registry.is_empty:
        return ""
    lines = ["## Available Skills\n"]
    for skill in registry.skills:
        desc = f" — {skill.description}" if skill.description else ""
        lines.append(f"- **{skill.name}**{desc} (`{skill.path}`)")
    lines.append(
        "\nUse `load_skill(name)` to read a skill's full instructions."
    )
    return "\n".join(lines)
