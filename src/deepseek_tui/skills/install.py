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
    "fetch_registry",
    "install",
    "uninstall",
    "update",
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
        return _install_from_github(source, target_dir, name_override)

    return (InstallOutcome.FAILED, f"Invalid source: {source.kind}")


def _install_from_github(
    source: InstallSource,
    target_dir: Path,
    name_override: str | None,
) -> tuple[InstallOutcome, str]:
    """Fetch a skill from GitHub (tarball download) and extract."""
    import io
    import tarfile
    import urllib.request

    name = name_override or source.repo
    dest = target_dir / name
    if dest.exists():
        return (InstallOutcome.ALREADY_EXISTS, f"Skill {name} already exists at {dest}")

    url = (
        f"https://github.com/{source.owner}/{source.repo}"
        f"/archive/refs/heads/main.tar.gz"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            data = resp.read()
    except Exception as exc:
        return (InstallOutcome.FAILED, f"Download failed: {exc}")

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            members = tf.getmembers()
            if not members:
                return (InstallOutcome.FAILED, "Empty archive")
            prefix = members[0].name.split("/", 1)[0]
            dest.mkdir(parents=True, exist_ok=True)
            for member in members:
                if member.name == prefix:
                    continue
                rel = member.name[len(prefix) + 1:]
                if not rel:
                    continue
                target = dest / rel
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    extracted = tf.extractfile(member)
                    if extracted:
                        target.write_bytes(extracted.read())
    except Exception as exc:
        if dest.exists():
            shutil.rmtree(dest)
        return (InstallOutcome.FAILED, f"Extract failed: {exc}")

    if not (dest / SKILL_FILENAME).is_file():
        shutil.rmtree(dest)
        return (InstallOutcome.FAILED, f"No {SKILL_FILENAME} in repo root")

    _write_installed_from(dest, f"github:{source.owner}/{source.repo}")
    return (InstallOutcome.INSTALLED, f"Installed {name} from GitHub")


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


def update(
    name: str, skills_dir: Path | None = None
) -> tuple[InstallOutcome, str]:
    """Re-install a community skill from its original source spec.

    Reads ``.installed-from`` to recover the source, then deletes and
    re-installs. Mirrors Rust ``update`` (install.rs:412-450).
    """
    target_dir = skills_dir or default_skills_dir()
    skill_path = target_dir / name
    if not skill_path.is_dir():
        return (InstallOutcome.FAILED, f"Skill not found: {name}")
    marker = skill_path / INSTALLED_FROM_MARKER
    if not marker.is_file():
        return (
            InstallOutcome.FAILED,
            f"Cannot update {name}: no {INSTALLED_FROM_MARKER} marker",
        )
    try:
        spec_data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (InstallOutcome.FAILED, f"Failed to read marker: {exc}")
    spec = spec_data.get("spec", "")
    if not spec:
        return (InstallOutcome.FAILED, "Empty spec in installed-from marker")

    # Preserve trust state across update
    trust_marker = skill_path / TRUSTED_MARKER
    was_trusted = trust_marker.is_file()

    source = InstallSource.parse(spec)
    if source.kind == "invalid":
        return (InstallOutcome.FAILED, f"Cannot parse stored spec: {spec}")

    shutil.rmtree(skill_path)
    outcome, message = install(source, skills_dir=target_dir, name_override=name)
    if outcome == InstallOutcome.INSTALLED:
        if was_trusted:
            (skill_path / TRUSTED_MARKER).touch()
        return (InstallOutcome.UPDATED, f"Updated {name} from {spec}")
    return (outcome, message)


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


def fetch_registry(url: str | None = None) -> RegistryDocument | None:
    """Fetch the remote skill registry index.

    Returns None on network/parse failure. Mirrors Rust
    ``fetch_registry`` (install.rs:450-470).
    """
    import urllib.request

    target = url or DEFAULT_REGISTRY_URL
    try:
        with urllib.request.urlopen(target, timeout=10) as resp:  # noqa: S310
            data = resp.read().decode("utf-8")
        return RegistryDocument.from_json(data)
    except Exception:
        _LOG.debug("Failed to fetch registry from %s", target)
        return None
