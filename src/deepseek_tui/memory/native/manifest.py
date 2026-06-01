"""Memory data-dir manifest and provenance records."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class ManifestMismatchError(RuntimeError):
    pass


class MemoryManifest:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / ".metadata" / "manifest.json"

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def ensure_store_binding(self, *, store_path: Path, **_kwargs: object) -> None:
        binding = {
            "backend": "sqlite",
            "store_path": str(store_path.expanduser().resolve()),
        }
        manifest = self.read()
        existing = manifest.get("store_binding")
        if isinstance(existing, dict):
            if existing.get("backend") != binding["backend"]:
                raise ManifestMismatchError(
                    f"memory data directory is bound to backend "
                    f"'{existing.get('backend')}', not '{binding['backend']}'"
                )
            if existing.get("store_path") != binding["store_path"]:
                raise ManifestMismatchError(
                    f"memory data directory is bound to store path "
                    f"'{existing.get('store_path')}', not '{binding['store_path']}'"
                )
        else:
            manifest["created_at"] = _now_iso()
            manifest["store_binding"] = binding
            manifest.setdefault("seed_runs", [])
            self.write(manifest)

    def record_seed_run(self, record: dict[str, Any]) -> None:
        manifest = self.read()
        manifest.setdefault("created_at", _now_iso())
        runs = manifest.get("seed_runs")
        if not isinstance(runs, list):
            runs = []
        runs.append({"recorded_at": _now_iso(), **record})
        manifest["seed_runs"] = runs[-20:]
        self.write(manifest)

    def write(self, manifest: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self._path)



def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
