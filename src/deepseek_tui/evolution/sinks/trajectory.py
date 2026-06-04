"""Optional trajectory JSONL sink — observe mutations without writing assets."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


class TrajectorySink:
    """Append-only observer for evolution ledger activity."""

    def __init__(self, path: Path) -> None:
        self._path = path.expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def observe(
        self,
        *,
        event: str,
        record_id: str | None = None,
        kind: str | None = None,
        source: str | None = None,
        thread_id: str | None = None,
        workspace: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        row = {
            "ts": time.time(),
            "event": event,
            "record_id": record_id,
            "kind": kind,
            "source": source,
            "thread_id": thread_id,
            "workspace": workspace,
            "payload": payload or {},
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def trajectory_sink_from_config(cfg: object) -> TrajectorySink | None:
    from deepseek_tui.config.models import Config

    if not isinstance(cfg, Config):
        return None
    sinks = cfg.evolution.sinks
    if not sinks.trajectory_enabled:
        return None
    if sinks.trajectory_path.strip():
        path = Path(sinks.trajectory_path).expanduser()
    else:
        from deepseek_tui.config.paths import user_deepseek_dir

        path = user_deepseek_dir() / "trajectories" / "evolution.jsonl"
    return TrajectorySink(path)


def _safe_payload(obj: object) -> dict[str, Any]:
    if isinstance(obj, dict):
        return dict(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return {"repr": repr(obj)}
