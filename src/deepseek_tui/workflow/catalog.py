"""Named workflow discovery and resolution.

Priority (higher wins on name collision):

1. ``<cwd>/workflows/<name>.json`` or ``<cwd>/workflows/<name>/spec.json``
2. ``<cwd>/.deepseek/workflows/`` (same shapes)
3. ``~/.deepseek/workflows/``
4. Package presets under ``workflow/presets/<name>.json``
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from deepseek_tui.config.paths import project_deepseek_dir, user_deepseek_dir
from deepseek_tui.workflow.models import (
    WorkflowSpec,
    WorkflowValidationError,
    parse_workflow_spec,
)

WorkflowSource = Literal["cwd", "project", "user", "preset"]

_NAME_RE_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


@dataclass(frozen=True, slots=True)
class WorkflowSpecRecord:
    name: str
    description: str
    source: WorkflowSource
    path: Path


class WorkflowCatalogError(WorkflowValidationError):
    """Named workflow could not be resolved."""


def _presets_dir() -> Path:
    return Path(__file__).resolve().parent / "presets"


def _is_safe_workflow_name(name: str) -> bool:
    if not name or len(name) > 64:
        return False
    return all(ch in _NAME_RE_OK for ch in name)


def _candidate_paths(root: Path, name: str) -> list[Path]:
    return [
        root / f"{name}.json",
        root / name / "spec.json",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkflowCatalogError(f"cannot read workflow {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise WorkflowCatalogError(f"workflow {path} is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowCatalogError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkflowCatalogError(f"workflow {path} must be a JSON object")
    return raw


def _meta_from_raw(raw: dict[str, Any], fallback_name: str) -> tuple[str, str]:
    meta = raw.get("meta")
    if isinstance(meta, dict):
        name = meta.get("name")
        description = meta.get("description")
        if isinstance(name, str) and name.strip():
            fallback_name = name.strip()
        if isinstance(description, str) and description.strip():
            return fallback_name, description.strip()
    return fallback_name, ""


def _discover_in_root(
    root: Path,
    *,
    source: WorkflowSource,
    seen: set[str],
) -> list[WorkflowSpecRecord]:
    if not root.is_dir():
        return []
    found: list[WorkflowSpecRecord] = []
    # Flat *.json — catalog name is the file stem (resolve_workflow looks up by path name).
    for path in sorted(root.glob("*.json")):
        name = path.stem
        if not _is_safe_workflow_name(name) or name in seen:
            continue
        try:
            raw = _read_json(path)
        except WorkflowCatalogError:
            continue
        _, description = _meta_from_raw(raw, name)
        seen.add(name)
        found.append(
            WorkflowSpecRecord(
                name=name,
                description=description or name,
                source=source,
                path=path,
            )
        )
    # Bundle dirs with spec.json
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        name = path.name
        if not _is_safe_workflow_name(name) or name in seen:
            continue
        spec_path = path / "spec.json"
        if not spec_path.is_file():
            continue
        try:
            raw = _read_json(spec_path)
        except WorkflowCatalogError:
            continue
        _, description = _meta_from_raw(raw, name)
        seen.add(name)
        found.append(
            WorkflowSpecRecord(
                name=name,
                description=description or name,
                source=source,
                path=spec_path,
            )
        )
    return found


def list_workflows(cwd: Path | None = None) -> list[WorkflowSpecRecord]:
    """List discoverable workflows; higher-priority roots win on name collision."""
    workspace = (cwd or Path.cwd()).resolve()
    seen: set[str] = set()
    records: list[WorkflowSpecRecord] = []
    roots: list[tuple[Path, WorkflowSource]] = [
        (workspace / "workflows", "cwd"),
        (project_deepseek_dir(workspace) / "workflows", "project"),
        (user_deepseek_dir() / "workflows", "user"),
        (_presets_dir(), "preset"),
    ]
    for root, source in roots:
        records.extend(_discover_in_root(root, source=source, seen=seen))
    return records


def resolve_workflow_path(name: str, cwd: Path | None = None) -> Path:
    """Return the winning path for a named workflow."""
    if not _is_safe_workflow_name(name):
        raise WorkflowCatalogError(f"invalid workflow name: {name!r}")
    workspace = (cwd or Path.cwd()).resolve()
    roots: list[Path] = [
        workspace / "workflows",
        project_deepseek_dir(workspace) / "workflows",
        user_deepseek_dir() / "workflows",
        _presets_dir(),
    ]
    for root in roots:
        for candidate in _candidate_paths(root, name):
            if candidate.is_file():
                return candidate
    raise WorkflowCatalogError(f"workflow not found: {name!r}")


def resolve_workflow(name: str, cwd: Path | None = None) -> WorkflowSpec:
    """Load and validate a named workflow spec."""
    path = resolve_workflow_path(name, cwd=cwd)
    raw = _read_json(path)
    return parse_workflow_spec(raw)
