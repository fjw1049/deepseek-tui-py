"""L0 JSONL incremental recorder."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from deepseek_tui.memory.formatting import sanitize_memory_text, strip_code_blocks
from deepseek_tui.memory.native.store import MemoryStore

_MIN_CONTENT_LEN = 4
_MAX_LINE_BYTES = 32_000


def _should_capture_l0(content: str) -> bool:
    text = sanitize_memory_text(content)
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
        """Append new L0 lines; return messages eligible for L1 extraction.

        Tool role messages are stored in L0 for audit/conversation_search but
        excluded from the returned list so they don't enter L1 extraction.
        """
        path = self._path_for(thread_id)
        last_ts, last_count = self._store.get_l0_cursor(thread_id)
        all_lines: list[dict[str, Any]] = []
        l1_eligible: list[dict[str, Any]] = []
        now_ms = int(time.time() * 1000)

        if _should_capture_l0(user_text):
            clean_user_text = sanitize_memory_text(user_text)
            record = {
                "id": f"msg_{now_ms}_user",
                "role": "user",
                "content": clean_user_text,
                "timestamp": now_ms,
                "workspace": workspace,
                "thread_id": thread_id,
                "sessionKey": thread_id,
                "sessionId": "",
                "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            all_lines.append(record)
            l1_eligible.append(record)

        for msg in messages:
            role = str(msg.get("role", ""))
            if role not in ("assistant", "tool"):
                continue
            content = str(msg.get("content", "") or "")
            if not _should_capture_l0(content):
                continue
            msg_ts = msg.get("timestamp") or now_ms
            if isinstance(msg_ts, (int, float)) and int(msg_ts) <= last_ts:
                continue
            clean_content = sanitize_memory_text(content)
            record = {
                "id": msg.get("id") or f"msg_{now_ms}_{role}",
                "role": role,
                "content": clean_content,
                "timestamp": msg_ts,
                "workspace": workspace,
                "thread_id": thread_id,
                "sessionKey": thread_id,
                "sessionId": "",
                "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            all_lines.append(record)
            if role != "tool":
                stripped = strip_code_blocks(clean_content)
                if stripped:
                    l1_record = {**record, "content": stripped}
                    l1_eligible.append(l1_record)
                else:
                    l1_eligible.append(record)

        if not all_lines:
            return []

        with path.open("a", encoding="utf-8") as handle:
            for line in all_lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")

        self._store.set_l0_cursor(
            thread_id,
            last_timestamp_ms=now_ms,
            last_message_count=last_count + len(all_lines),
        )
        return l1_eligible

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
