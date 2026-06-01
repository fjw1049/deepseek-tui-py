"""TTL cleanup for native memory artifacts."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from deepseek_tui.memory.native.store import MemoryStore


@dataclass(slots=True)
class CleanupResult:
    l0_deleted: int = 0
    l0_rewritten: int = 0
    l1_deleted: int = 0


class MemoryCleaner:
    def __init__(self, data_dir: Path, store: MemoryStore) -> None:
        self._data_dir = data_dir
        self._store = store
        self._l0_dir = data_dir / "l0"

    def run(self, *, retention_days: int) -> CleanupResult:
        if retention_days <= 0:
            return CleanupResult()
        cutoff_ms = int(time.time() * 1000) - retention_days * 86_400_000
        result = CleanupResult()
        result.l1_deleted = self._store.delete_memories_older_than(cutoff_ms)
        l0_deleted, l0_rewritten = self._clean_l0(cutoff_ms)
        result.l0_deleted = l0_deleted
        result.l0_rewritten = l0_rewritten
        return result

    def _clean_l0(self, cutoff_ms: int) -> tuple[int, int]:
        if not self._l0_dir.is_dir():
            return (0, 0)
        deleted = 0
        rewritten = 0
        for path in sorted(self._l0_dir.glob("*.jsonl")):
            keep: list[str] = []
            removed = 0
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for raw in lines:
                if not raw.strip():
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    keep.append(raw)
                    continue
                try:
                    ts = int(float(data.get("timestamp", 0) or 0))
                except (TypeError, ValueError):
                    ts = 0
                if ts and ts < cutoff_ms:
                    removed += 1
                    continue
                keep.append(json.dumps(data, ensure_ascii=False))
            if not keep:
                path.unlink(missing_ok=True)
                deleted += removed
            elif removed:
                path.write_text("\n".join(keep) + "\n", encoding="utf-8")
                deleted += removed
                rewritten += 1
        return (deleted, rewritten)
