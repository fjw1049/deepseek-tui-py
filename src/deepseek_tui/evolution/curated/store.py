"""Curated MEMORY.md / USER.md store."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from deepseek_tui.evolution.safety import scan_memory_content

SECTION = "\n§\n"
Target = Literal["memory", "user"]


@dataclass(frozen=True)
class CuratedSnapshot:
    memory_block: str | None
    user_block: str | None


class CuratedMemoryStore:
    """Bounded curated memory with frozen prompt snapshot and live tool state."""

    def __init__(
        self,
        curated_dir: Path,
        *,
        memory_char_limit: int = 2200,
        user_char_limit: int = 1375,
    ) -> None:
        self._dir = curated_dir.expanduser()
        self._memory_path = self._dir / "MEMORY.md"
        self._user_path = self._dir / "USER.md"
        self._memory_char_limit = memory_char_limit
        self._user_char_limit = user_char_limit
        self.memory_entries: list[str] = []
        self.user_entries: list[str] = []
        self._snapshot: CuratedSnapshot | None = None

    @property
    def memory_path(self) -> Path:
        return self._memory_path

    @property
    def user_path(self) -> Path:
        return self._user_path

    def load_snapshot(self) -> CuratedSnapshot:
        self.memory_entries = self._read_entries(self._memory_path)
        self.user_entries = self._read_entries(self._user_path)
        self.memory_entries = _dedupe_entries(self.memory_entries)
        self.user_entries = _dedupe_entries(self.user_entries)
        snap = CuratedSnapshot(
            memory_block=self._format_block("memory", self.memory_entries)
            if self.memory_entries
            else None,
            user_block=self._format_block("user", self.user_entries)
            if self.user_entries
            else None,
        )
        self._snapshot = snap
        return snap

    def stable_prompt_block(self) -> str | None:
        if self._snapshot is None:
            self.load_snapshot()
        assert self._snapshot is not None
        parts: list[str] = []
        if self._snapshot.memory_block:
            parts.append(self._snapshot.memory_block)
        if self._snapshot.user_block:
            parts.append(self._snapshot.user_block)
        return "\n\n".join(parts) if parts else None

    def live_entries(self, target: Target) -> list[str]:
        return list(self._entries_for(target))

    def usage(self, target: Target) -> str:
        current = self._char_count(target)
        limit = self._char_limit(target)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0
        return f"{pct}% — {current:,}/{limit:,} chars"

    def add(self, target: Target, content: str) -> dict[str, object]:
        content = content.strip()
        if not content:
            return {"ok": False, "error": "content cannot be empty"}
        ok, reason = scan_memory_content(content)
        if not ok:
            return {"ok": False, "error": reason}
        path = self._path_for(target)
        with self._file_lock(path):
            self._reload_target(target)
            entries = self._entries_for(target)
            if content in entries:
                return self._success_response(
                    target, message="entry already exists (no duplicate added)"
                )
            limit = self._char_limit(target)
            new_entries = [*entries, content]
            new_total = len(SECTION.join(new_entries))
            if new_total > limit:
                current = self._char_count(target)
                return {
                    "ok": False,
                    "error": (
                        f"Memory at {current:,}/{limit:,} chars. "
                        f"Adding this entry ({len(content)} chars) would exceed the limit. "
                        "Replace or remove existing entries first."
                    ),
                    "current_entries": list(entries),
                    "usage": self.usage(target),
                }
            self._set_entries(target, new_entries)
            self._save_target(target)
        return self._success_response(target, message="entry added")

    def replace(self, target: Target, old_text: str, content: str) -> dict[str, object]:
        old_text = old_text.strip()
        new_content = content.strip()
        if not old_text:
            return {"ok": False, "error": "old_text cannot be empty"}
        if not new_content:
            return {"ok": False, "error": "content cannot be empty; use remove to delete"}
        ok, reason = scan_memory_content(new_content)
        if not ok:
            return {"ok": False, "error": reason}
        path = self._path_for(target)
        with self._file_lock(path):
            self._reload_target(target)
            entries = self._entries_for(target)
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
            if not matches:
                return {"ok": False, "error": f"no entry matched '{old_text}'"}
            if len(matches) > 1:
                unique = {e for _, e in matches}
                if len(unique) > 1:
                    previews = [e[:80] + ("…" if len(e) > 80 else "") for _, e in matches]
                    return {
                        "ok": False,
                        "error": f"multiple entries matched '{old_text}'; be more specific",
                        "matches": previews,
                    }
            idx = matches[0][0]
            limit = self._char_limit(target)
            test_entries = entries.copy()
            test_entries[idx] = new_content
            if len(SECTION.join(test_entries)) > limit:
                return {
                    "ok": False,
                    "error": (
                        f"replacement would exceed {limit:,} char limit; "
                        "shorten content or remove other entries first"
                    ),
                    "usage": self.usage(target),
                }
            entries[idx] = new_content
            self._set_entries(target, entries)
            self._save_target(target)
        return self._success_response(target, message="entry replaced")

    def remove(self, target: Target, old_text: str) -> dict[str, object]:
        old_text = old_text.strip()
        if not old_text:
            return {"ok": False, "error": "old_text cannot be empty"}
        path = self._path_for(target)
        with self._file_lock(path):
            self._reload_target(target)
            entries = self._entries_for(target)
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
            if not matches:
                return {"ok": False, "error": f"no entry matched '{old_text}'"}
            if len(matches) > 1:
                unique = {e for _, e in matches}
                if len(unique) > 1:
                    previews = [e[:80] + ("…" if len(e) > 80 else "") for _, e in matches]
                    return {
                        "ok": False,
                        "error": f"multiple entries matched '{old_text}'; be more specific",
                        "matches": previews,
                    }
            entries.pop(matches[0][0])
            self._set_entries(target, entries)
            self._save_target(target)
        return self._success_response(target, message="entry removed")

    def _path_for(self, target: Target) -> Path:
        return self._memory_path if target == "memory" else self._user_path

    def _entries_for(self, target: Target) -> list[str]:
        return self.memory_entries if target == "memory" else self.user_entries

    def _set_entries(self, target: Target, entries: list[str]) -> None:
        if target == "memory":
            self.memory_entries = entries
        else:
            self.user_entries = entries

    def _char_limit(self, target: Target) -> int:
        return self._memory_char_limit if target == "memory" else self._user_char_limit

    def _char_count(self, target: Target) -> int:
        entries = self._entries_for(target)
        if not entries:
            return 0
        return len(SECTION.join(entries))

    def _reload_target(self, target: Target) -> None:
        path = self._path_for(target)
        entries = _dedupe_entries(self._read_entries(path))
        self._set_entries(target, entries)

    def _save_target(self, target: Target) -> None:
        path = self._path_for(target)
        body = SECTION.join(self._entries_for(target))
        self._atomic_write(path, body)

    def _read_entries(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        return [b.strip() for b in text.split(SECTION) if b.strip()]

    @staticmethod
    @contextmanager
    def _file_lock(path: Path) -> Iterator[None]:
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("w", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def _success_response(self, target: Target, *, message: str) -> dict[str, object]:
        entries = self.live_entries(target)
        return {
            "ok": True,
            "action": message,
            "target": target,
            "current_entries": entries,
            "entry_count": len(entries),
            "usage": self.usage(target),
            "message": message,
        }

    def _format_block(self, target: Target, entries: list[str]) -> str:
        if not entries:
            return ""
        label = "Curated Agent Memory" if target == "memory" else "Curated User Profile"
        body = SECTION.join(entries)
        usage = self.usage(target) if entries else ""
        header = f"## {label}"
        if usage:
            header = f"{header} [{usage}]"
        return f"{header}\n\n{body.strip()}"


def _dedupe_entries(entries: list[str]) -> list[str]:
    return list(dict.fromkeys(entries))
