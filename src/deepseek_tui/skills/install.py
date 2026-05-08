"""Skill installation, update, and uninstall.

Mirrors ``crates/tui/src/skills/install.rs``. Handles community skill
install from source specs (``github:owner/repo``) and local tarballs,
plus update/uninstall/trust lifecycle.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from deepseek_tui.skills import (
    INSTALLED_FROM_MARKER,
    SKILL_FILENAME,
    TRUSTED_MARKER,
    default_skills_dir,
)

__all__ = [
    "InstallOutcome",
    "InstallSource",
    "RegistryDocument",
    "RegistryEntry",
    "install",
    "uninstall",
    "trust",
]

_LOG = logging.getLogger(__name__)

DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/deepseek-ai/"
    "DeepSeek-TUI/main/skills-registry/index.json"
)


class InstallOutcome(str, Enum):
    INSTALLED = "installed"
    ALREADY_EXISTS = "already_exists"
    UPDATED = "updated"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class InstallSource:
    """Parsed install source spec.

    Mirrors Rust ``InstallSource::parse``.
    """

    kind: str
    owner: str = ""
    repo: str = ""
    local_path: str = ""

    @classmethod
    def parse(cls, spec: str) -> InstallSource:
        spec = spec.strip()
        if spec.startswith("github:"):
            parts = spec[len("github:"):].split("/", 1)
            if len(parts) == 2:
                return cls(kind="github", owner=parts[0], repo=parts[1])
            return cls(kind="invalid")
        if Path(spec).is_dir():
            return cls(kind="local", local_path=spec)
        return cls(kind="invalid")


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """One row in the curated registry index.json."""

    source: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class RegistryDocument:
    """Deserialized registry index.json."""

    skills: dict[str, RegistryEntry]

    @classmethod
    def from_json(cls, data: str) -> RegistryDocument:
        raw = json.loads(data)
        skills: dict[str, RegistryEntry] = {}
        for name, entry in raw.get("skills", {}).items():
            skills[name] = RegistryEntry(
                source=entry.get("source", ""),
                description=entry.get("description", ""),
            )
        return cls(skills=skills)


def install(
    source: InstallSource,
    skills_dir: Path | None = None,
    name_override: str | None = None,
) -> tuple[InstallOutcome, str]:
    """Install a skill from a source spec.

    Returns (outcome, message). Network-based install (GitHub) is P1
    integration debt — requires HTTP client. Local copy is supported now.
    """
    target_dir = skills_dir or default_skills_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    if source.kind == "local":
        src = Path(source.local_path)
        skill_file = src / SKILL_FILENAME
        if not skill_file.is_file():
            return (
                InstallOutcome.FAILED,
                f"No {SKILL_FILENAME} found in {src}",
            )
        name = name_override or src.name
        dest = target_dir / name
        if dest.exists():
            return (
                InstallOutcome.ALREADY_EXISTS,
                f"Skill {name} already exists at {dest}",
            )
        shutil.copytree(src, dest)
        _write_installed_from(dest, f"local:{src}")
        return (InstallOutcome.INSTALLED, f"Installed {name} to {dest}")

    if source.kind == "github":
        return (
            InstallOutcome.FAILED,
            f"GitHub install ({source.owner}/{source.repo}) "
            "requires HTTP client — P1 integration debt",
        )

    return (InstallOutcome.FAILED, f"Invalid source: {source.kind}")


def uninstall(name: str, skills_dir: Path | None = None) -> str:
    """Uninstall a community skill (must have .installed-from marker).

    Mirrors Rust ``uninstall`` (install.rs:390-410).
    """
    target_dir = skills_dir or default_skills_dir()
    skill_path = target_dir / name
    if not skill_path.is_dir():
        return f"Skill not found: {name}"
    marker = skill_path / INSTALLED_FROM_MARKER
    if not marker.is_file():
        return (
            f"Cannot uninstall {name}: no {INSTALLED_FROM_MARKER} marker "
            "(may be a system or manually installed skill)"
        )
    shutil.rmtree(skill_path)
    return f"Uninstalled {name}"


def trust(name: str, skills_dir: Path | None = None) -> str:
    """Mark a community skill as trusted.

    Mirrors Rust ``trust`` (install.rs:420-440).
    """
    target_dir = skills_dir or default_skills_dir()
    skill_path = target_dir / name
    if not skill_path.is_dir():
        return f"Skill not found: {name}"
    marker = skill_path / INSTALLED_FROM_MARKER
    if not marker.is_file():
        return f"Cannot trust {name}: not a community install"
    (skill_path / TRUSTED_MARKER).touch()
    return f"Trusted {name}"


def _write_installed_from(dest: Path, source_spec: str) -> None:
    """Write the .installed-from marker file."""
    marker = dest / INSTALLED_FROM_MARKER
    marker.write_text(
        json.dumps({"spec": source_spec}, indent=2),
        encoding="utf-8",
    )
