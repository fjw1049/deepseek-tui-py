from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from deepseek_tui.plugins.model import ResourceRef
from deepseek_tui.plugins.source import LocalArtifact, PackageCandidate, PluginSourceError

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginSourceError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PluginSourceError(f"expected JSON object at {path}")
    return value


def markdown_metadata(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text.strip()
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise PluginSourceError(f"invalid YAML frontmatter at {path}: {exc}") from exc
    if not isinstance(metadata, dict):
        metadata = {}
    return metadata, text[match.end() :].strip()


def resource_ref(candidate: PackageCandidate, path: Path) -> ResourceRef:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(candidate.root.resolve()).as_posix()
    except ValueError as exc:
        raise PluginSourceError(f"resource escapes package root: {path}") from exc
    media_type = "text/markdown" if path.suffix.lower() == ".md" else "application/json"
    return ResourceRef(relative, media_type)


def declared_paths(
    artifact: LocalArtifact,
    candidate: PackageCandidate,
    value: object,
) -> list[Path]:
    raw_values = [value] if isinstance(value, str) else value
    if not isinstance(raw_values, list):
        return []
    paths: list[Path] = []
    for raw in raw_values:
        if not isinstance(raw, str):
            continue
        normalized = raw[2:] if raw.startswith("./") else raw
        path = artifact.resolve(candidate.root, normalized)
        if path.exists():
            paths.append(path)
    return paths


def markdown_files(paths: list[Path], *, skill: bool = False) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".md":
            files.append(path)
        elif path.is_dir() and skill and (path / "SKILL.md").is_file():
            files.append(path / "SKILL.md")
        elif path.is_dir():
            for found in path.rglob("SKILL.md" if skill else "*.md"):
                if ".git" in found.relative_to(path).parts:
                    continue
                files.append(found)
    return sorted(set(files))


def scalar_description(value: object) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else ""
