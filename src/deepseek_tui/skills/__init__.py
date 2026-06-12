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
    "agents_global_skills_dir",
    "claude_global_skills_dir",
    "default_skills_dir",
    "discover_in_workspace",
    "invalidate_skills_prompt_cache",
    "render_available_skills_context",
    "skills_directories",
]

_skills_prompt_cache_token = 0


def invalidate_skills_prompt_cache() -> None:
    """Bump skills prompt cache generation after skill writes."""
    global _skills_prompt_cache_token
    _skills_prompt_cache_token += 1

_LOG = logging.getLogger(__name__)

SKILL_FILENAME = "SKILL.md"
INSTALLED_FROM_MARKER = ".installed-from"
TRUSTED_MARKER = ".trusted"
SYSTEM_VERSION_MARKER = ".system-installed-version"


def default_skills_dir() -> Path:
    """``~/.deepseek/skills`` — user-level skill registry.

    Stage 3.3 will add project-level overlay (``<ws>/.deepseek/skills``).
    """
    from deepseek_tui.config.paths import user_skills_dir

    return user_skills_dir()


def agents_global_skills_dir() -> Path | None:
    """``~/.agents/skills`` — agentskills.io ecosystem global.

    Mirrors Rust ``agents_global_skills_dir`` (skills/mod.rs:41-43).
    """
    home = Path.home()
    if not home:
        return None
    return home / ".agents" / "skills"


def claude_global_skills_dir() -> Path | None:
    """``~/.claude/skills`` — Claude-ecosystem global (#902).

    Mirrors Rust ``claude_global_skills_dir`` (skills/mod.rs:51-53).
    """
    home = Path.home()
    if not home:
        return None
    return home / ".claude" / "skills"


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

    Mirrors Rust ``skills_directories`` (skills/mod.rs:371-408). Precedence
    (first match wins on name conflicts):

    1. ``<workspace>/.agents/skills`` — deepseek-native convention.
    2. ``<workspace>/skills`` — flat, project-local.
    3. ``<workspace>/.opencode/skills`` — OpenCode interop.
    4. ``<workspace>/.claude/skills`` — Claude Code interop.
    5. ``<workspace>/.cursor/skills`` — Cursor interop.
    6. ``agents_global_skills_dir`` — agentskills.io global.
    7. ``claude_global_skills_dir`` — Claude-ecosystem global (#902).
    8. ``default_skills_dir`` — DeepSeek global, user-installed.

    An explicit ``skills_dir`` override (tests, CLI flag) is honored first
    so deterministic precedence holds for callers that pin a directory.

    De-duplication uses ``Path.resolve()`` so two paths that canonicalize
    to the same dir (symlink chains, ``./foo`` vs ``foo``) are merged.
    """
    dirs: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path | None) -> None:
        if p is None:
            return
        try:
            canonical = p.resolve()
        except OSError:
            return
        if canonical.is_dir() and canonical not in seen:
            dirs.append(p)
            seen.add(canonical)

    if skills_dir is not None:
        _add(skills_dir)

    if workspace:
        _add(workspace / ".agents" / "skills")
        _add(workspace / "skills")
        _add(workspace / ".deepseek" / "skills")
        _add(workspace / ".opencode" / "skills")
        _add(workspace / ".claude" / "skills")
        _add(workspace / ".cursor" / "skills")

    _add(agents_global_skills_dir())
    _add(claude_global_skills_dir())
    if skills_dir is None:
        _add(default_skills_dir())
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

MAX_SKILL_DESCRIPTION_CHARS = 500
MAX_AVAILABLE_SKILLS_CHARS = 12_000

_HOW_TO_USE_SKILLS = (
    "\n### How to use skills\n"
    "- Discovery: The list above is the skills available in this session. "
    "Skill bodies live on disk at the listed paths.\n"
    "- Trigger rules: If the user names a skill (with `$SkillName`, "
    "`/skill <name>`, or plain text) OR the task clearly matches a skill "
    "description above, use that skill for that turn. Multiple mentions "
    "mean use them all. Do not carry skills across turns unless re-mentioned.\n"
    "- Missing/blocked: If a named skill is missing or its `SKILL.md` cannot "
    "be read, say so briefly and continue with the best fallback.\n"
    "- Progressive disclosure: After deciding to use a skill, call "
    "`load_skill(name=...)` to read its full instructions. When it references "
    "relative paths such as `scripts/foo.py`, resolve them relative to the "
    "skill directory.\n"
    "- Context hygiene: Load only the specific referenced files needed for "
    "the task. Avoid bulk-loading unrelated skill resources.\n"
    "- Safety: Do not execute scripts from a community skill unless the user "
    "explicitly asks or the skill has been trusted for script use.\n"
)


def truncate_for_prompt(value: str, max_chars: int) -> str:
    """Collapse internal whitespace, then bound by ``max_chars``.

    Mirrors Rust ``truncate_for_prompt`` (mod.rs:565). The collapse is
    deliberate: SKILL.md descriptions sometimes carry stray newlines /
    tabs / runs of spaces, and the system-prompt section reads as a
    single bullet list, not free-form prose.
    """
    single_line = " ".join(value.split())
    if len(single_line) <= max_chars:
        return single_line
    if max_chars <= 1:
        return "…"
    return single_line[: max_chars - 1] + "…"


def render_available_skills_context(
    registry: SkillRegistry,
) -> str:
    """Render the progressive-disclosure skills block for the system prompt.

    Mirrors Rust ``render_skills_block`` (mod.rs:497-562). Each entry
    carries the real on-disk path captured at discovery — the directory
    name can differ from the frontmatter ``name`` for community installs,
    in which case ``<dir>/<name>/SKILL.md`` would not exist and the model
    would fail to open it.
    """
    if registry.is_empty:
        return ""

    parts: list[str] = ["## Skills\n"]
    parts.append(
        "A skill is a set of local instructions stored in a `SKILL.md` file. "
        "Below is the list of skills available in this session. Each entry "
        "includes a name, description, and file path so you can open the "
        "source for full instructions when using a specific skill.\n\n"
    )
    parts.append("### Available skills\n")

    rendered_lines: list[str] = []
    omitted = 0
    running = sum(len(p) for p in parts)
    for skill in registry.skills:
        desc = truncate_for_prompt(skill.description, MAX_SKILL_DESCRIPTION_CHARS)
        line = (
            f"- {skill.name}: (file: {skill.path})\n"
            if not desc
            else f"- {skill.name}: {desc} (file: {skill.path})\n"
        )
        if running + len(line) > MAX_AVAILABLE_SKILLS_CHARS:
            omitted += 1
        else:
            rendered_lines.append(line)
            running += len(line)
    parts.extend(rendered_lines)

    if omitted > 0:
        parts.append(
            f"- ... {omitted} additional skills omitted from this prompt budget.\n"
        )

    if registry.warnings:
        parts.append("\n### Skill load warnings\n")
        for warning in registry.warnings[:8]:
            parts.append(
                f"- {truncate_for_prompt(warning, MAX_SKILL_DESCRIPTION_CHARS)}\n"
            )

    parts.append(_HOW_TO_USE_SKILLS)
    return "".join(parts)
