"""L3 persona — aggregate persona-type L1 rows into persona.md."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.memory.native.store import MemoryStore


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
    lines = ["# Persona (auto-generated from L1 memories)", ""]
    for row in rows:
        lines.append(f"- {row.content}")
    persona_path.parent.mkdir(parents=True, exist_ok=True)
    persona_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True
