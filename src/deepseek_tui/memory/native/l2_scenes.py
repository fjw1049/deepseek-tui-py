"""L2 scene blocks — markdown files + JSON index (lite TencentDB parity)."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _safe_filename(name: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name.strip())[:80]
    return slug or "scene"


@dataclass(slots=True)
class SceneIndexEntry:
    name: str
    filename: str
    workspace: str | None
    updated_at: int


class SceneStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._blocks_dir = data_dir / "scene_blocks"
        self._index_path = data_dir / ".metadata" / "scene_index.json"
        self._blocks_dir.mkdir(parents=True, exist_ok=True)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)

    def record_scenes(
        self,
        scenes: list[dict[str, Any]],
        *,
        workspace: str,
    ) -> int:
        """Upsert scene blocks from L1 extraction JSON."""
        index = self._load_index()
        written = 0
        now = int(time.time() * 1000)
        for scene in scenes:
            name = str(scene.get("scene_name", "") or "").strip()
            if not name:
                continue
            filename = f"{_safe_filename(name)}.md"
            path = self._blocks_dir / filename
            memories = scene.get("memories") or []
            lines = [f"# {name}", "", f"workspace: {workspace}", ""]
            if isinstance(memories, list):
                for mem in memories:
                    if isinstance(mem, dict) and mem.get("content"):
                        lines.append(f"- {mem['content']}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            entry = SceneIndexEntry(
                name=name,
                filename=filename,
                workspace=workspace,
                updated_at=now,
            )
            index = [e for e in index if e.filename != filename]
            index.append(entry)
            written += 1
        if written:
            self._save_index(index)
        return written

    def navigation_markdown(self, *, workspace: str | None, limit: int = 8) -> str:
        index = self._load_index()
        if workspace:
            index = [e for e in index if e.workspace == workspace or e.workspace is None]
        if not index:
            return ""
        index.sort(key=lambda e: e.updated_at, reverse=True)
        lines = ["## Scene navigation (L2)", ""]
        for entry in index[:limit]:
            path = self._blocks_dir / entry.filename
            lines.append(f"### {entry.name}")
            lines.append(f"Path: {path.resolve()}")
            lines.append("")
        return "\n".join(lines).strip()

    def _load_index(self) -> list[SceneIndexEntry]:
        if not self._index_path.is_file():
            return []
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[SceneIndexEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            out.append(
                SceneIndexEntry(
                    name=str(item.get("name", "")),
                    filename=str(item.get("filename", "")),
                    workspace=item.get("workspace"),
                    updated_at=int(item.get("updated_at", 0)),
                )
            )
        return out

    def _save_index(self, entries: list[SceneIndexEntry]) -> None:
        payload = [
            {
                "name": e.name,
                "filename": e.filename,
                "workspace": e.workspace,
                "updated_at": e.updated_at,
            }
            for e in entries
        ]
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
