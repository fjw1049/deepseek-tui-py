from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from deepseek_tui.goal.models import GoalEntry, GoalStatus, ThreadGoal
from deepseek_tui.goal.state import reconstruct_goal, set_entry, update_status

_GENERIC_SESSION_IDS = frozenset({"current", "latest", "default", ""})


def safe_thread_id(thread_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in thread_id)


def goal_journal_path(workspace: Path, thread_id: str) -> Path:
    return workspace.resolve() / ".deepseek" / "goals" / f"{safe_thread_id(thread_id)}.jsonl"


def resolve_goal_thread_id(
    metadata: dict,
    *,
    fallback_id: str,
    workspace: Path,
) -> str:
    """Pick the journal key for resume/rebind, including legacy session files."""
    goals_dir = workspace.resolve() / ".deepseek" / "goals"
    candidates: list[str] = []
    for key in ("id", "memory_thread_id"):
        val = metadata.get(key)
        if isinstance(val, str):
            text = val.strip()
            if text and text.lower() not in _GENERIC_SESSION_IDS:
                candidates.append(text)
    fallback = fallback_id.strip()
    if fallback and fallback.lower() not in _GENERIC_SESSION_IDS:
        candidates.append(fallback)

    for candidate in candidates:
        if goal_journal_path(workspace, candidate).exists():
            return candidate

    for key in ("id", "memory_thread_id"):
        val = metadata.get(key)
        if isinstance(val, str):
            text = val.strip()
            if text and text.lower() not in _GENERIC_SESSION_IDS:
                return text

    if goals_dir.is_dir():
        journals = [p for p in goals_dir.glob("*.jsonl") if p.stat().st_size > 0]
        if len(journals) == 1:
            return journals[0].stem

    if candidates:
        return candidates[0]
    return fallback or "default"


def copy_goal_journal_file(
    source: Path,
    target: Path,
    *,
    pause_reason: str = "paused after thread fork",
) -> None:
    """Copy a journal file and pause any active goal on the fork branch."""
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    journal = GoalJournal(target)
    goal = journal.load_goal()
    if goal is not None and goal.status == GoalStatus.ACTIVE:
        journal.append(
            set_entry(
                update_status(goal, GoalStatus.PAUSED, reason=pause_reason),
            )
        )


def copy_goal_journal_for_fork(
    workspace: Path,
    source_thread_id: str,
    target_thread_id: str,
    *,
    pause_reason: str = "paused after thread fork",
) -> None:
    """TUI/workspace fork helper under ``.deepseek/goals/``."""
    copy_goal_journal_file(
        goal_journal_path(workspace, source_thread_id),
        goal_journal_path(workspace, target_thread_id),
        pause_reason=pause_reason,
    )


class GoalJournal:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_workspace(cls, workspace: Path, thread_id: str) -> GoalJournal:
        return cls(goal_journal_path(workspace, thread_id))

    def read_entries(self) -> list[GoalEntry]:
        if not self.path.exists():
            return []
        entries: list[GoalEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(GoalEntry.from_json(json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
        return entries

    def load_goal(self) -> ThreadGoal | None:
        return reconstruct_goal(self.read_entries())

    def append(self, entry: GoalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry.to_json(), ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
