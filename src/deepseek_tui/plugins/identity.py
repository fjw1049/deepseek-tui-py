"""Plugin identity and path safety helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PluginIdentityError(ValueError):
    pass


def validate_plugin_id(value: str) -> str:
    """Return a safe plugin id or raise :class:`PluginIdentityError`."""
    name = (value or "").strip()
    if not _PLUGIN_ID.fullmatch(name) or name in {".", ".."}:
        raise PluginIdentityError(
            "plugin id must be 1-128 chars of [A-Za-z0-9._-] and not '.'/'..'"
        )
    if "/" in name or "\\" in name or "\x00" in name:
        raise PluginIdentityError(f"unsafe plugin id: {value!r}")
    return name


def is_safe_plugin_id(value: str) -> bool:
    try:
        validate_plugin_id(value)
    except PluginIdentityError:
        return False
    return True


def is_safe_relative_posix(path: str) -> bool:
    if not path or "\\" in path or "\x00" in path:
        return False
    parsed = PurePosixPath(path)
    return not parsed.is_absolute() and ".." not in parsed.parts


def content_fingerprint(root: Path, *, max_files: int = 20_000) -> str:
    """Fast invalidate key: relative path + mtime + size (no file bodies)."""
    resolved = root.expanduser().resolve()
    digest = hashlib.sha256()
    count = 0
    for path in sorted(resolved.rglob("*")):
        if ".git" in path.relative_to(resolved).parts:
            continue
        if path.is_symlink() or path.is_dir():
            continue
        count += 1
        if count > max_files:
            raise PluginIdentityError(f"plugin exceeds {max_files} files for fingerprint")
        relative = path.relative_to(resolved).as_posix()
        try:
            stat = path.stat()
        except OSError as exc:
            raise PluginIdentityError(f"cannot fingerprint {relative}") from exc
        digest.update(relative.encode("utf-8"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(str(stat.st_size).encode("ascii"))
    return f"fp:{digest.hexdigest()}"


def source_content_digest(
    root: Path,
    *,
    provenance: dict | None = None,
    max_files: int = 20_000,
    max_bytes: int = 50 * 1024 * 1024,
) -> str:
    """Return the store content digest (``sha256:...``) for a plugin tree.

    Prefers ``provenance.source.digest`` / ``content_digest`` when already a
    ``sha256:`` value (install/update lockfile). Otherwise hashes file bodies
    via :class:`~deepseek_tui.plugins.source.LocalArtifact` — the same key
    used by the content-addressed store. Do **not** use
    :func:`content_fingerprint` for authorization binding.
    """
    if isinstance(provenance, dict):
        source = provenance.get("source")
        if isinstance(source, dict):
            digest = source.get("digest")
            if isinstance(digest, str) and digest.startswith("sha256:"):
                return digest
        content_digest = provenance.get("content_digest")
        if isinstance(content_digest, str) and content_digest.startswith("sha256:"):
            return content_digest
    from deepseek_tui.plugins.source import LocalArtifact, PluginSourceError

    try:
        return LocalArtifact(root, max_files=max_files, max_bytes=max_bytes).digest
    except PluginSourceError as exc:
        raise PluginIdentityError(str(exc)) from exc
