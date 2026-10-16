"""Notice repeated agent browser workflows and suggest keeping them as skills."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THRESHOLD = 3
MAX_PATTERNS = 200
NAVIGATION = {"open", "navigate", "new_tab", "switch_tab"}


def signature(doc: Any, site: str) -> str | None:
    """The workflow's shape on one site; values are masked and never part of it."""
    shape, interactions = [], 0
    for step in doc.steps:
        if step.kind in NAVIGATION:
            shape.append([step.kind])
            continue
        interactions += 1
        target = step.target or {}
        label = target.get("name") or target.get("label") or target.get("placeholder") or ""
        shape.append([step.kind, target.get("role", ""), str(label).strip().lower()[:80],
                      step.key or ""])
    if interactions < 2:
        return None
    return hashlib.sha256(json.dumps([site, shape]).encode()).hexdigest()[:16]


class SkillSuggestions:
    """Counts workflow shapes across chats; keeps only each shape's latest capture."""

    def __init__(self, path: Path):
        self.path = path
        self.pending: dict[str, dict[str, Any]] = {}
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("enabled", True)
        self.data.setdefault("patterns", {})

    @property
    def enabled(self) -> bool:
        return self.data["enabled"] is True

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def set_enabled(self, enabled: bool) -> None:
        self.data["enabled"] = enabled
        if not enabled:
            self.pending.clear()
        self._save()

    def observe(
        self, thread_id: str, recording_id: str, doc: Any, site: str, covered: set[str]
    ) -> list[tuple[str, str]]:
        """Count a completed capture; returns the captures that are no longer needed."""
        key = signature(doc, site)
        if key is None:
            return [(thread_id, recording_id)]
        patterns = self.data["patterns"]
        entry = patterns.setdefault(key, {"site": site, "count": 0})
        discard = [tuple(entry.pop("recording"))] if entry.get("recording") else []
        entry["count"] += 1
        entry["updated"] = datetime.now(timezone.utc).isoformat()
        if entry.get("closed"):
            discard.append((thread_id, recording_id))
        else:
            entry["recording"] = [thread_id, recording_id]
        for old in sorted(patterns, key=lambda k: patterns[k]["updated"])[:-MAX_PATTERNS]:
            if patterns[old].get("recording"):
                discard.append(tuple(patterns[old]["recording"]))
            del patterns[old]
        for owner, recording in discard:
            pending = self.pending.get(owner)
            if pending and pending["recording_id"] == recording:
                del self.pending[owner]
        self._save()
        if (entry.get("recording") and entry["count"] >= THRESHOLD and site not in covered
                and self.enabled):
            self.pending[thread_id] = {"id": key, "site": site, "count": entry["count"],
                                       "recording_id": recording_id}
        return discard

    def resolve(self, thread_id: str, accepted: bool) -> dict[str, Any]:
        suggestion = self.pending.pop(thread_id, None)
        if suggestion is None:
            raise ValueError("No skill suggestion for this chat")
        entry = self.data["patterns"].get(suggestion["id"])
        if entry is not None:
            entry["closed"] = "accepted" if accepted else "dismissed"
            self._save()
        return suggestion
