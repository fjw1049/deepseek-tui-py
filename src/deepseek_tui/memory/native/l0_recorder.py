"""L0 JSONL incremental recorder."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from deepseek_tui.memory.formatting import strip_relevant_memories
from deepseek_tui.memory.native.store import MemoryStore

_MIN_CONTENT_LEN = 4
_MAX_LINE_BYTES = 32_000


def _should_capture_l0(content: str) -> bool:
    text = strip_relevant_memories(content).strip()
    if len(text) < _MIN_CONTENT_LEN:
        return False
    if len(text.encode("utf-8")) > _MAX_LINE_BYTES:
        return False
    return True


class L0Recorder:
    def __init__(self, l0_dir: Path, store: MemoryStore) -> None:
        self._l0_dir = l0_dir
        self._store = store
        self._l0_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, thread_id: str) -> Path:
        safe = thread_id.replace("/", "_")
        return self._l0_dir / f"{safe}.jsonl"

    def append_turn(
        self,
        thread_id: str,
        *,
        user_text: str,
        messages: list[dict[str, Any]],
        workspace: str,
    ) -> list[dict[str, Any]]:
        """Append new L0 lines; return messages eligible for L1 extraction."""
        path = self._path_for(thread_id)
        last_ts, last_count = self._store.get_l0_cursor(thread_id)
        new_lines: list[dict[str, Any]] = []
        now_ms = int(time.time() * 1000)

        if _should_capture_l0(user_text):
            new_lines.append(
                {
                    "id": f"msg_{now_ms}_user",
                    "role": "user",
                    "content": strip_relevant_memories(user_text),
                    "timestamp": now_ms,
                    "workspace": workspace,
                }
            )

        for msg in messages:
            role = str(msg.get("role", ""))
            if role not in ("assistant", "tool"):
                continue
            content = str(msg.get("content", "") or "")
            if not _should_capture_l0(content):
                continue
            new_lines.append(
                {
                    "id": msg.get("id") or f"msg_{now_ms}_{role}",
                    "role": role,
                    "content": strip_relevant_memories(content),
                    "timestamp": msg.get("timestamp") or now_ms,
                    "workspace": workspace,
                }
            )

        if not new_lines:
            return []

        with path.open("a", encoding="utf-8") as handle:
            for line in new_lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")

        self._store.set_l0_cursor(
            thread_id,
            last_timestamp_ms=now_ms,
            last_message_count=last_count + len(new_lines),
        )
        return new_lines

    def read_recent(self, thread_id: str, *, max_lines: int = 80) -> list[dict[str, Any]]:
        path = self._path_for(thread_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for raw in lines[-max_lines:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return out
