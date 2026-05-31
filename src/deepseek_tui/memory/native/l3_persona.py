"""L3 persona — aggregate persona-type L1 rows into persona.md."""

from __future__ import annotations

import hashlib
from pathlib import Path

from deepseek_tui.memory.native.store import MemoryStore


def _workspace_key(workspace: str) -> str:
    return hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:16]


def persona_path_for_workspace(persona_path: Path, *, workspace: str | None) -> Path:
    if not workspace:
        return persona_path
    return persona_path.parent / "persona" / f"{_workspace_key(workspace)}.md"


def persona_paths_for_workspace(
    persona_path: Path, *, workspace: str | None
) -> list[Path]:
    if not workspace:
        return [persona_path]
    return [persona_path_for_workspace(persona_path, workspace=workspace)]


def refresh_persona_from_store(
    store: MemoryStore,
    persona_path: Path,
    *,
    workspace: str | None = None,
    limit: int = 40,
) -> bool:
    """Rebuild ``persona.md`` from L1 persona memories. Returns True if written."""
    rows = store.list_memories_by_type("persona", workspace=workspace, limit=limit)
    if not rows:
        return False
    target_path = persona_path_for_workspace(persona_path, workspace=workspace)
    lines = ["# Persona (auto-generated from L1 memories)", ""]
    for row in rows:
        lines.append(f"- {row.content}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True
