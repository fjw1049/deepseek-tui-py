"""Content-addressed plugin-host storage (v2).

Immutable source trees live under ``plugin-host/sources/sha256/<digest>/``.
Scope directories (``~/.deepseek/plugins/<name>``) preferably symlink into the
store so updates can switch digests without rewriting vendor bytes.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import user_deepseek_dir
from deepseek_tui.plugins.model import DerivedPlugin
from deepseek_tui.plugins.source import LocalArtifact, PluginSourceError
from deepseek_tui.utils import write_json_atomic

_HEX = re.compile(r"^[0-9a-f]{64}$")


def plugin_host_root(home: Path | None = None) -> Path:
    return (home or user_deepseek_dir()) / "plugin-host"


def sources_root(home: Path | None = None) -> Path:
    return plugin_host_root(home) / "sources" / "sha256"


def source_path(digest: str, *, home: Path | None = None) -> Path:
    return sources_root(home) / _normalize_digest(digest)


def derived_path(
    digest: str,
    adapter_id: str,
    *,
    home: Path | None = None,
) -> Path:
    hex_digest = _normalize_digest(digest)
    safe_adapter = _safe_segment(adapter_id)
    return plugin_host_root(home) / "derived" / "v1" / hex_digest / f"{safe_adapter}.json"


def report_path(
    digest: str,
    adapter_id: str,
    *,
    home: Path | None = None,
) -> Path:
    hex_digest = _normalize_digest(digest)
    safe_adapter = _safe_segment(adapter_id)
    return plugin_host_root(home) / "reports" / hex_digest / f"{safe_adapter}.json"


def publish_source_tree(
    src: Path,
    *,
    home: Path | None = None,
    max_files: int = 20_000,
    max_bytes: int = 50 * 1024 * 1024,
) -> tuple[str, Path]:
    """Copy *src* into the content-addressed store. Returns ``(digest, path)``."""
    artifact = LocalArtifact(src, max_files=max_files, max_bytes=max_bytes)
    digest = artifact.digest
    dest = source_path(digest, home=home)
    if dest.is_dir():
        return digest, dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = dest.parent
    with tempfile.TemporaryDirectory(prefix=".publish-", dir=staging_parent) as tmp:
        staging = Path(tmp) / "tree"
        try:
            shutil.copytree(src, staging, symlinks=False, ignore_dangling_symlinks=True)
        except OSError as exc:
            raise PluginSourceError(f"cannot publish plugin source: {exc}") from exc
        # Re-validate the staged tree before publish.
        LocalArtifact(staging, max_files=max_files, max_bytes=max_bytes)
        os_replace = dest
        try:
            staging.rename(os_replace)
        except OSError:
            if dest.exists():
                return digest, dest
            shutil.move(str(staging), str(dest))
    return digest, dest


def link_or_copy_from_store(
    store_path: Path,
    dest: Path,
) -> str:
    """Materialize *dest* as a symlink to the store, falling back to copy.

    Returns ``"symlink"`` or ``"copy"``.
    """
    if dest.exists():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.symlink_to(store_path, target_is_directory=True)
        return "symlink"
    except OSError:
        shutil.copytree(store_path, dest)
        return "copy"


def write_derived(plugin: DerivedPlugin, *, home: Path | None = None) -> Path:
    path = derived_path(
        plugin.source.digest,
        plugin.compatibility.adapter_id,
        home=home,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, plugin.to_dict())
    report = report_path(
        plugin.source.digest,
        plugin.compatibility.adapter_id,
        home=home,
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(report, plugin.compatibility.to_dict())
    return path


def read_derived(
    digest: str,
    adapter_id: str,
    *,
    home: Path | None = None,
) -> dict[str, Any] | None:
    path = derived_path(digest, adapter_id, home=home)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def referenced_source_digests(
    *,
    home: Path | None = None,
    workspaces: list[Path] | None = None,
) -> set[str]:
    """Collect digests still referenced by lockfiles / live scope links."""
    from deepseek_tui.integrations.plugins import (
        plugins_directories,
        read_lockfile,
        user_plugins_dir,
    )

    digests: set[str] = set()
    roots = list(plugins_directories(None, None))
    if workspaces:
        for workspace in workspaces:
            roots.extend(plugins_directories(None, workspace))
    roots.append(user_plugins_dir())
    seen_roots: set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen_roots or not resolved.is_dir():
            continue
        seen_roots.add(resolved)
        lock = read_lockfile(resolved)
        for entry in lock.values():
            if not isinstance(entry, dict):
                continue
            provenance = entry.get("derived_provenance")
            if isinstance(provenance, dict):
                source = provenance.get("source")
                if isinstance(source, dict) and source.get("digest"):
                    digests.add(_normalize_digest(str(source["digest"])))
            if entry.get("content_digest"):
                digests.add(_normalize_digest(str(entry["content_digest"])))
        for child in resolved.iterdir():
            if not child.is_symlink():
                continue
            try:
                target = child.resolve()
            except OSError:
                continue
            parts = target.parts
            if "sources" in parts and "sha256" in parts:
                try:
                    idx = parts.index("sha256")
                    digests.add(parts[idx + 1])
                except (ValueError, IndexError):
                    continue
    return digests


def gc_unreferenced_sources(
    *,
    home: Path | None = None,
    workspaces: list[Path] | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Delete source trees that no lockfile/symlink references.

    Returns the list of removed (or would-remove) digests.
    """
    root = sources_root(home)
    if not root.is_dir():
        return []
    live = referenced_source_digests(home=home, workspaces=workspaces)
    removed: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not _HEX.fullmatch(child.name):
            continue
        if child.name in live:
            continue
        removed.append(child.name)
        if not dry_run:
            shutil.rmtree(child, ignore_errors=True)
            derived = plugin_host_root(home) / "derived" / "v1" / child.name
            reports = plugin_host_root(home) / "reports" / child.name
            shutil.rmtree(derived, ignore_errors=True)
            shutil.rmtree(reports, ignore_errors=True)
    return removed


def rollback_plugin_link(
    plugins_dir: Path,
    plugin_name: str,
    digest: str,
    *,
    home: Path | None = None,
) -> Path:
    """Point ``plugins_dir/plugin_name`` at an existing store digest."""
    store = source_path(digest, home=home)
    if not store.is_dir():
        raise FileNotFoundError(f"store digest not found: {digest}")
    dest = plugins_dir / plugin_name
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)
    link_or_copy_from_store(store, dest)
    return dest


def _normalize_digest(digest: str) -> str:
    value = digest.strip()
    if value.startswith("sha256:"):
        value = value[7:]
    if value.startswith("fp:"):
        value = value[3:]
    if not _HEX.fullmatch(value):
        import hashlib

        value = hashlib.sha256(digest.encode("utf-8")).hexdigest()
    return value


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()) or "adapter"
    if ".." in cleaned:
        raise ValueError(f"unsafe path segment: {value!r}")
    return cleaned
