"""Read-only local artifacts and package location."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.plugins.model import Diagnostic, DiagnosticSeverity


class PluginSourceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PackageCandidate:
    root: Path
    relative_root: str
    declared_name: str = ""
    marketplace_entry: dict[str, Any] = field(default_factory=dict)


class LocalArtifact:
    def __init__(
        self,
        root: Path,
        *,
        max_files: int = 20_000,
        max_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        resolved = root.expanduser().resolve()
        if not resolved.is_dir():
            raise PluginSourceError(f"plugin source is not a directory: {root}")
        self.root = resolved
        self.digest = self._digest(max_files=max_files, max_bytes=max_bytes)

    def _digest(self, *, max_files: int, max_bytes: int) -> str:
        digest = hashlib.sha256()
        count = 0
        total_bytes = 0
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root).as_posix()
            if ".git" in path.relative_to(self.root).parts:
                continue
            if path.is_symlink():
                target = path.resolve()
                try:
                    target.relative_to(self.root)
                except ValueError as exc:
                    raise PluginSourceError(
                        f"plugin symlink escapes source root: {relative}"
                    ) from exc
            if path.is_dir():
                continue
            count += 1
            if count > max_files:
                raise PluginSourceError(f"plugin source contains more than {max_files} files")
            try:
                total_bytes += path.stat().st_size
            except OSError as exc:
                raise PluginSourceError(f"cannot stat plugin file: {relative}") from exc
            if total_bytes > max_bytes:
                raise PluginSourceError(
                    f"plugin source exceeds inspection limit of {max_bytes} bytes"
                )
            digest.update(relative.encode("utf-8"))
            try:
                digest.update(path.read_bytes())
            except OSError as exc:
                raise PluginSourceError(f"cannot read plugin file: {relative}") from exc
        return f"sha256:{digest.hexdigest()}"

    def resolve(self, package_root: Path, relative: str) -> Path:
        if not relative or "\x00" in relative or "\\" in relative:
            raise PluginSourceError(f"unsafe package path: {relative!r}")
        candidate = (package_root / relative).resolve()
        try:
            candidate.relative_to(package_root.resolve())
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PluginSourceError(f"package path escapes root: {relative!r}") from exc
        return candidate


def _manifest_roots(root: Path) -> set[Path]:
    markers = (
        ".claude-plugin/plugin.json",
        ".codebuddy-plugin/plugin.json",
        ".deepseek-plugin/plugin.json",
    )
    roots: set[Path] = set()
    for marker in markers:
        for path in root.rglob(marker):
            if ".git" not in path.relative_to(root).parts:
                roots.add(path.parent.parent.resolve())
    return roots


def _marketplace_candidates(
    artifact: LocalArtifact,
) -> tuple[list[PackageCandidate], list[Diagnostic]] | None:
    marketplace_path = artifact.root / ".claude-plugin" / "marketplace.json"
    if not marketplace_path.is_file():
        marketplace_path = artifact.root / "marketplace.json"
    if not marketplace_path.is_file():
        return None
    try:
        document = json.loads(marketplace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginSourceError(f"invalid marketplace JSON: {exc}") from exc

    candidates: list[PackageCandidate] = []
    diagnostics: list[Diagnostic] = []
    for index, entry in enumerate(document.get("plugins", [])):
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        if isinstance(source, str):
            try:
                package_root = artifact.resolve(artifact.root, source)
            except PluginSourceError as exc:
                diagnostics.append(
                    Diagnostic(
                        "MARKETPLACE_SOURCE_REJECTED",
                        DiagnosticSeverity.ERROR,
                        str(exc),
                        source_path=f"plugins[{index}].source",
                    )
                )
                continue
            if not package_root.is_dir():
                diagnostics.append(
                    Diagnostic(
                        "MARKETPLACE_SOURCE_MISSING",
                        DiagnosticSeverity.ERROR,
                        f"marketplace source does not exist: {source}",
                        source_path=f"plugins[{index}].source",
                    )
                )
                continue
            candidates.append(
                PackageCandidate(
                    root=package_root,
                    relative_root=package_root.relative_to(artifact.root).as_posix(),
                    declared_name=str(entry.get("name") or ""),
                    marketplace_entry=entry,
                )
            )
        elif isinstance(source, dict):
            candidates.append(
                PackageCandidate(
                    root=artifact.root,
                    relative_root=f"remote:{entry.get('name') or index}",
                    declared_name=str(entry.get("name") or ""),
                    marketplace_entry=entry,
                )
            )
            diagnostics.append(
                Diagnostic(
                    "REMOTE_MARKETPLACE_SOURCE_NOT_FETCHED",
                    DiagnosticSeverity.INFO,
                    "remote marketplace entry was catalogued but not fetched",
                    source_path=f"plugins[{index}].source",
                    remediation="install or inspect the remote source explicitly",
                )
            )
    return candidates, diagnostics


def locate_packages(
    artifact: LocalArtifact,
) -> tuple[list[PackageCandidate], list[Diagnostic]]:
    marketplace = _marketplace_candidates(artifact)
    if marketplace is not None:
        return marketplace

    marker_roots = _manifest_roots(artifact.root)
    roots = set(marker_roots)
    conventional_root = any(
        (artifact.root / path).exists()
        for path in ("skills", "commands", "agents", "hooks/hooks.json", ".mcp.json")
    )
    if conventional_root:
        roots.add(artifact.root)

    for skill_file in artifact.root.rglob("SKILL.md"):
        parent = skill_file.parent.resolve()
        if any(parent == root or root in parent.parents for root in roots):
            continue
        roots.add(parent)

    candidates = [
        PackageCandidate(
            root=root,
            relative_root=(
                "." if root == artifact.root else root.relative_to(artifact.root).as_posix()
            ),
        )
        for root in sorted(roots)
    ]
    return candidates, []
