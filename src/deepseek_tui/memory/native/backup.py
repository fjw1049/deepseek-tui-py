"""Small backup helper for L2/L3 memory artifacts."""

from __future__ import annotations

import shutil
import time
from pathlib import Path


class BackupManager:
    def __init__(self, data_dir: Path, *, max_keep: int = 10) -> None:
        self._backup_dir = data_dir / ".backup"
        self._max_keep = max(1, max_keep)

    def backup_file(self, path: Path, label: str) -> Path | None:
        if not path.is_file():
            return None
        target_dir = self._backup_dir / label
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{_stamp()}_{path.name}"
        shutil.copy2(path, target)
        self._prune(target_dir)
        return target

    def backup_directory(self, path: Path, label: str) -> Path | None:
        if not path.is_dir():
            return None
        target_dir = self._backup_dir / label
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / _stamp()
        shutil.copytree(path, target, dirs_exist_ok=True)
        self._prune(target_dir)
        return target

    def _prune(self, target_dir: Path) -> None:
        entries = sorted(
            target_dir.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in entries[self._max_keep :]:
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
            else:
                old.unlink(missing_ok=True)


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())
