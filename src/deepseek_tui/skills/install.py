"""Skill installation, update, and uninstall.

Mirrors ``crates/tui/src/skills/install.rs``. Handles community skill
install from source specs (``github:owner/repo``) and local tarballs,
plus update/uninstall/trust lifecycle.

2026-05-14 — Hardened against the audit report's K-1/K-2/K-3/K-4/K-5/K-7
findings (HANDOVER §skills.2026-05-14):

* K-1: streaming download with a 5 MiB cap, plus a separate cap on the
  cumulative decompressed size. Prevents gzip-bomb OOM.
* K-2: host allow-list (``github.com`` / ``www.github.com``) for GitHub
  installs; ``main`` → ``master`` branch fallback.
* K-3: explicit path-traversal guard — every extracted target is
  ``resolve().relative_to(dest_resolved)`` checked.
* K-4: explicit symlink reject (logged + skipped, no silent pass-through).
* K-5: robust top-level prefix detection via ``Path.parts[0]`` rather
  than ``split("/", 1)[0]``.
* K-7: nested SKILL.md layout — accept either ``dest/SKILL.md`` or
  ``dest/<name>/SKILL.md`` as a valid install root.

Network IO uses ``httpx`` (already a project dependency) instead of
``urllib.request`` so timeouts / streaming / connection pooling come
from the same client the rest of the system uses.
"""
from __future__ import annotations

import io
import json
import logging
import shutil
import tarfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from deepseek_tui.skills import (
    INSTALLED_FROM_MARKER,
    SKILL_FILENAME,
    TRUSTED_MARKER,
    default_skills_dir,
)

__all__ = [
    "DEFAULT_MAX_SIZE_BYTES",
    "GITHUB_ALLOWED_HOSTS",
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

# 5 MiB matches Rust ``DEFAULT_MAX_SIZE_BYTES`` (install.rs:66). Applied
# both to the compressed download stream AND to the cumulative
# decompressed bytes — a gzip-bomb wins the first check but fails the
# second.
DEFAULT_MAX_SIZE_BYTES = 5 * 1024 * 1024

# Mirrors Rust install.rs:144 — only these hosts are accepted for
# ``github:`` archive URLs. Anything else fails ``_resolve_archive_urls``.
GITHUB_ALLOWED_HOSTS = frozenset({"github.com", "www.github.com"})

# Hosts we accept for the public skill registry index. Matches
# DEFAULT_REGISTRY_URL host; can be overridden by the caller passing an
# explicit URL with one of these hosts.
REGISTRY_ALLOWED_HOSTS = frozenset(
    {"raw.githubusercontent.com", "github.com", "www.github.com"}
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


# ── Install entrypoint ───────────────────────────────────────────────────


def install(
    source: InstallSource,
    skills_dir: Path | None = None,
    name_override: str | None = None,
    *,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
) -> tuple[InstallOutcome, str]:
    """Install a skill from a source spec.

    Returns (outcome, message).
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
        return _install_from_github(
            source, target_dir, name_override, max_size_bytes=max_size_bytes
        )

    return (InstallOutcome.FAILED, f"Invalid source: {source.kind}")


def _github_archive_urls(source: InstallSource) -> list[str]:
    """Candidate archive URLs in fallback order (main → master).

    Mirrors Rust install.rs which tries main then master via
    ``download_first_success`` (install.rs:295).
    """
    base = f"https://github.com/{source.owner}/{source.repo}/archive/refs/heads"
    return [f"{base}/main.tar.gz", f"{base}/master.tar.gz"]


def _host_is_allowed(url: str, allow: frozenset[str]) -> bool:
    """K-2: reject URLs not in the host allow-list."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        return False
    host = (parsed.hostname or "").lower()
    return host in allow


def _install_from_github(
    source: InstallSource,
    target_dir: Path,
    name_override: str | None,
    *,
    max_size_bytes: int,
) -> tuple[InstallOutcome, str]:
    """Fetch a skill from GitHub (tarball download) and extract.

    Hardened path. See module docstring for K-1..K-7 notes.

    Extraction is **atomic**: tarball lands in a sibling ``.<name>.tmp``
    directory; a successful, validated extract is then ``rename``-d into
    place. A mid-flight failure (Ctrl-C, network error, bomb, traversal
    attempt) leaves no half-baked ``dest/`` behind that the user has to
    ``rm -rf`` before retrying. Mirrors the Rust install path's
    tempdir-then-rename pattern.
    """
    name = name_override or source.repo
    dest = target_dir / name
    if dest.exists():
        return (InstallOutcome.ALREADY_EXISTS, f"Skill {name} already exists at {dest}")

    urls = _github_archive_urls(source)
    # K-2: every candidate URL must clear the host allow-list. Since we
    # only construct them from github.com, this is belt-and-suspenders —
    # but if a future caller injects an arbitrary URL here, the guard
    # holds.
    urls = [u for u in urls if _host_is_allowed(u, GITHUB_ALLOWED_HOSTS)]
    if not urls:
        return (InstallOutcome.FAILED, "No allowed archive URLs for source")

    data: bytes | None = None
    source_url: str | None = None
    last_error: str = ""
    for candidate in urls:
        try:
            data = _stream_download(candidate, max_size_bytes)
            source_url = candidate
            break
        except _DownloadTooLarge as exc:
            return (InstallOutcome.FAILED, f"Download exceeds {max_size_bytes} bytes: {exc}")
        except _DownloadMissing:
            last_error = f"{candidate}: not found"
            continue
        except Exception as exc:  # noqa: BLE001 — surface any failure
            last_error = f"{candidate}: {exc}"
            continue

    if data is None or source_url is None:
        return (InstallOutcome.FAILED, f"Download failed: {last_error or 'unknown error'}")

    staging = target_dir / f".{name}.tmp"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    try:
        _extract_tarball(data, staging, max_size_bytes=max_size_bytes)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"Extract failed: {exc}")

    # K-7: accept either ``staging/SKILL.md`` (flat) or
    # ``staging/<single-subdir>/SKILL.md`` (nested) as a valid layout.
    if not _has_skill_file(staging):
        shutil.rmtree(staging, ignore_errors=True)
        return (
            InstallOutcome.FAILED,
            f"No {SKILL_FILENAME} in repo (looked at top level and one nested dir)",
        )

    _write_installed_from(staging, f"github:{source.owner}/{source.repo}")

    # Atomic publish. ``os.rename`` is atomic on POSIX when source and
    # destination live on the same filesystem (they do — both under
    # ``target_dir``). A concurrent installer racing to the same ``dest``
    # may lose; we leave the staging dir intact for retry in that case.
    try:
        staging.rename(dest)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"Atomic rename failed: {exc}")

    return (
        InstallOutcome.INSTALLED,
        f"Installed {name} from GitHub ({source_url})",
    )


def _has_skill_file(dest: Path) -> bool:
    """K-7: SKILL.md may live at dest root or one level deeper."""
    if (dest / SKILL_FILENAME).is_file():
        return True
    if not dest.is_dir():
        return False
    for child in dest.iterdir():
        if child.is_dir() and (child / SKILL_FILENAME).is_file():
            return True
    return False


# ── Download ────────────────────────────────────────────────────────────


class _DownloadTooLarge(Exception):
    """K-1: stream exceeded the cap."""


class _DownloadMissing(Exception):
    """HTTP 404 — try the next candidate URL."""


def _stream_download(url: str, max_bytes: int, *, timeout: float = 30.0) -> bytes:
    """K-1: read the response in chunks, abort when over ``max_bytes``.

    Returns the full body on success. Raises ``_DownloadTooLarge`` when
    the stream exceeds the cap. Raises ``_DownloadMissing`` on 404 so
    the caller can try the next fallback URL.
    """
    buf = bytearray()
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            if resp.status_code == 404:
                raise _DownloadMissing(url)
            resp.raise_for_status()
            for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise _DownloadTooLarge(
                        f"{len(buf)} bytes read (max {max_bytes})"
                    )
    return bytes(buf)


# ── Extract ─────────────────────────────────────────────────────────────


def _extract_tarball(data: bytes, dest: Path, *, max_size_bytes: int) -> None:
    """Extract a GitHub-style ``.tar.gz`` into *dest*.

    Hardened with K-3 (path-traversal guard), K-4 (symlink reject),
    K-5 (robust prefix detection), and a cumulative decompressed-size
    cap to defuse gzip bombs that pass the on-the-wire cap.
    """
    dest_resolved = dest.resolve() if dest.exists() else dest.absolute()
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        members = tf.getmembers()
        if not members:
            raise ValueError("Empty archive")

        # K-5: detect a top-level directory prefix. We look at *all*
        # members and check if every name shares the same first segment.
        # That covers: dir-first archives (the common case), file-first
        # archives, archives whose first entry happens to be a symlink
        # (which is itself rejected later, but still informs prefix
        # detection), etc.
        candidate_prefixes = set()
        for m in members:
            parts = Path(m.name).parts
            if not parts:
                candidate_prefixes.add("")
                break
            candidate_prefixes.add(parts[0])
            if len(candidate_prefixes) > 1:
                break
        if len(candidate_prefixes) == 1:
            (only,) = candidate_prefixes
            # If the only member is itself the prefix path with no slash
            # (e.g. a single root file ``foo.txt``), don't treat the file
            # name as a prefix — that would strip everything.
            single_root_file = (
                len(members) == 1
                and members[0].isfile()
                and "/" not in members[0].name
            )
            prefix = "" if single_root_file else only
        else:
            prefix = ""

        decompressed_total = 0
        for member in members:
            # K-4: symlinks (and hardlinks) are an obvious vector to
            # escape ``dest`` regardless of how careful the path math is.
            # Reject + log.
            if member.issym() or member.islnk():
                _LOG.warning(
                    "skipping symlink/hardlink in skill archive: %s -> %s",
                    member.name,
                    member.linkname,
                )
                continue

            # Strip the top-level prefix. If the archive doesn't have one
            # (single-file root), use the name as-is.
            if prefix:
                rel = _strip_prefix(member.name, prefix)
            else:
                rel = member.name
            if not rel:
                continue

            # K-3: explicit path-traversal guard. Resolve the candidate
            # path and verify it lives under ``dest_resolved``. ``..``
            # segments and absolute paths trip this.
            candidate = (dest / rel).resolve(strict=False)
            try:
                candidate.relative_to(dest_resolved)
            except ValueError as exc:
                raise ValueError(
                    f"path traversal attempt rejected: {member.name!r}"
                ) from exc

            if member.isdir():
                candidate.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                # Devices, FIFOs, etc. — silently skip but log.
                _LOG.debug("skipping non-regular member: %s", member.name)
                continue

            # Cumulative decompressed-size cap (gzip-bomb defuse).
            decompressed_total += int(member.size or 0)
            if decompressed_total > max_size_bytes:
                raise _DownloadTooLarge(
                    f"decompressed size > {max_size_bytes} bytes"
                )

            candidate.parent.mkdir(parents=True, exist_ok=True)
            extracted = tf.extractfile(member)
            if extracted is not None:
                candidate.write_bytes(extracted.read())


def _strip_prefix(name: str, prefix: str) -> str:
    """Strip a top-level directory prefix from a tar member name.

    Handles edge cases that the old ``name[len(prefix) + 1:]`` formula
    got wrong:

    * ``name == prefix`` → returns ``""`` (the prefix dir itself).
    * ``name.startswith(prefix + "/")`` → strips ``prefix/``.
    * No match → returns the original name (don't drop characters).
    """
    if name == prefix:
        return ""
    head = f"{prefix}/"
    if name.startswith(head):
        return name[len(head):]
    return name


# ── Lifecycle ───────────────────────────────────────────────────────────


def uninstall(name: str, skills_dir: Path | None = None) -> str:
    """Uninstall a community skill (must have .installed-from marker)."""
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
    """Re-install a community skill from its original source spec."""
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
    """Mark a community skill as trusted."""
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
    marker = dest / INSTALLED_FROM_MARKER
    marker.write_text(
        json.dumps({"spec": source_spec}, indent=2),
        encoding="utf-8",
    )


def fetch_registry(url: str | None = None) -> RegistryDocument | None:
    """Fetch the remote skill registry index.

    Returns None on network/parse failure. Host allow-listed for
    safety — passing a URL whose host isn't in ``REGISTRY_ALLOWED_HOSTS``
    returns None (logged).
    """
    target = url or DEFAULT_REGISTRY_URL
    if not _host_is_allowed(target, REGISTRY_ALLOWED_HOSTS):
        _LOG.warning("registry host not allow-listed: %s", target)
        return None
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(target)
            resp.raise_for_status()
            return RegistryDocument.from_json(resp.text)
    except Exception:
        _LOG.debug("Failed to fetch registry from %s", target)
        return None


# ── Backwards-compat helpers used by tests ──────────────────────────────


def _read_test_archive(path: Path) -> bytes:
    """Tiny helper kept here so tests don't have to know the internal
    layout — read a fixture tarball into bytes."""
    return path.read_bytes()


def install_from_bytes(
    archive_bytes: bytes,
    spec: str,
    skills_dir: Path,
    name: str,
    *,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
) -> tuple[InstallOutcome, str]:
    """Test seam: install from a tarball passed inline.

    Bypasses the network so the K-3..K-7 extract path can be unit-tested
    end-to-end without spinning a fake HTTP server. Atomic-publish path
    mirrors ``_install_from_github`` — staging dir + ``rename``.
    """
    dest = skills_dir / name
    if dest.exists():
        return (InstallOutcome.ALREADY_EXISTS, f"Skill {name} already exists at {dest}")
    skills_dir.mkdir(parents=True, exist_ok=True)
    staging = skills_dir / f".{name}.tmp"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    try:
        _extract_tarball(archive_bytes, staging, max_size_bytes=max_size_bytes)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"Extract failed: {exc}")
    if not _has_skill_file(staging):
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"No {SKILL_FILENAME} in archive")
    _write_installed_from(staging, spec)
    try:
        staging.rename(dest)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return (InstallOutcome.FAILED, f"Atomic rename failed: {exc}")
    return (InstallOutcome.INSTALLED, f"Installed {name} to {dest}")


def __getattr__(name: str) -> Any:  # pragma: no cover — friendly errors
    raise AttributeError(name)
